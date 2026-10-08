"""Self-service personal Meta OAuth with ownership and single-use state."""
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import urlencode
import uuid
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from config.settings import settings
from core.auth import require_meta_self
from core.database import get_db
from core.tenant import tenant_scope, effective_tenant_id
from models import Credential, MetaAccount, MetaOAuthSession, User
from services.meta.oauth_service import MetaOAuthService, MetaOAuthError
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from services.meta_connection_service import bind_connection, owned_connection

router = APIRouter(prefix="/api/v1/meta-auth", tags=["Meta OAuth 授权"])


class SDKLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=20)
    connection_id: str | None = None


class OAuthClaimRequest(BaseModel):
    state: str
    receipt: str


class OAuthAccountsCompleteRequest(BaseModel):
    credential_id: str
    account_ids: list[str] = Field(..., min_length=1)


class OAuthCompleteRequest(BaseModel):
    credential_id: str
    business_id: str


def _frontend_redirect(**params):
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL.rstrip('/')}/dashboard/accounts?{urlencode(params)}", status_code=302)


def _oauth_return_to(request, requested=None):
    allowed = {"https://iornix.com", "http://49.232.238.163:8094", settings.FRONTEND_BASE_URL.rstrip("/")}
    candidate = str(requested or "").rstrip("/")
    return candidate if candidate in allowed else settings.FRONTEND_BASE_URL.rstrip("/")


def _new_oauth_state(user, tenant_id, meta_account_id=None, return_to=None, *, db=None, connection_id=None):
    now = datetime.utcnow()
    nonce = uuid.uuid4().hex
    payload = {"purpose": "meta_oauth", "sub": user.id, "tid": tenant_id, "jti": nonce,
               "iat": now, "exp": now + timedelta(minutes=10), "return_to": return_to}
    if meta_account_id:
        payload["meta_account_id"] = meta_account_id
    if db is not None:
        db.add(MetaOAuthSession(id=nonce, tenant_id=tenant_id, user_id=user.id,
                               connection_id=connection_id, expires_at=now + timedelta(minutes=10)))
        db.commit()
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _consume_state(db, state, user=None):
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp", "sub", "tid", "jti"]})
        if payload.get("purpose") != "meta_oauth":
            raise jwt.InvalidTokenError()
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="授权 state 无效或已过期") from exc
    if user and (payload["sub"] != user.id or payload["tid"] != effective_tenant_id(user)):
        raise HTTPException(status_code=403, detail="授权回调不属于当前用户或租户")
    with tenant_scope(payload["tid"]):
        intent = db.query(MetaOAuthSession).filter_by(id=payload["jti"], user_id=payload["sub"], tenant_id=payload["tid"]).first()
        if not intent or intent.consumed_at or intent.expires_at <= datetime.utcnow():
            raise HTTPException(status_code=400, detail="授权回调已处理或已过期，请重新发起")
        updated = db.query(MetaOAuthSession).filter(MetaOAuthSession.id == intent.id,
                    MetaOAuthSession.consumed_at.is_(None)).update({"consumed_at": datetime.utcnow()}, synchronize_session=False)
        if updated != 1:
            raise HTTPException(status_code=400, detail="授权回调已处理")
        return payload, intent.connection_id


def _store_direct(db, user, token, scopes, connection_id=None):
    row = bind_connection(db, user, {**token, "app_id": settings.FB_APP_ID, "scopes": scopes},
                          mode="direct", expected_connection_id=connection_id)
    query = db.query(Credential).filter_by(connection_id=row.id, granted_by_user_id=user.id)
    cred = query.filter_by(id=row.credential_id).first() if row.credential_id else query.order_by(Credential.updated_at.desc()).first()
    if not cred:
        pending_id = uuid.uuid4().hex
        db.add(MetaAccount(id=pending_id, tenant_id=row.tenant_id, name="个人 Meta 授权",
            business_id=f"__oauth_pending__{pending_id}", app_id=settings.FB_APP_ID, status="ARCHIVED", sync_status="PENDING"))
        db.flush()
        cred = Credential(id=uuid.uuid4().hex, tenant_id=row.tenant_id, meta_account_id=pending_id,
            token_type="USER", expires_at=token.get("expires_at"), source="OAUTH",
            scopes=scopes, granted_by_user_id=user.id, meta_user_id=row.meta_user_id)
        db.add(cred)
        cred.name = f"个人 Meta OAuth - {user.username}"
    cred.set_access_token(token["access_token"])
    cred.connection_id = row.id
    cred.app_id = row.app_id
    cred.status = "ACTIVE"
    cred.scopes = scopes
    cred.expires_at = row.expires_at
    cred.last_verified_at = datetime.utcnow()
    row.credential_id = cred.id
    db.flush()
    return row


@router.get("/mode")
def auth_mode(_: User = Depends(require_meta_self)):
    return {"access_mode": settings.FB_ACCESS_MODE}


@router.get("/sdk-config")
def sdk_config(_: User = Depends(require_meta_self)):
    if settings.FB_ACCESS_MODE == "connector":
        try:
            return FBConnectorClient().sdk_config()
        except FBConnectorError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not settings.FB_APP_ID:
        raise HTTPException(status_code=503, detail="Meta App ID 未配置")
    return {"app_id": settings.FB_APP_ID, "version": settings.FB_API_VERSION, "login_config_id": settings.FB_LOGIN_CONFIG_ID or None}


@router.post("/sdk-login")
def sdk_login(payload: SDKLoginRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    if payload.connection_id:
        owned_connection(db, current_user, connection_id=payload.connection_id)
    try:
        if settings.FB_ACCESS_MODE == "connector":
            result = FBConnectorClient().sdk_login(payload.access_token)
            row = bind_connection(db, current_user, result, mode="connector", expected_connection_id=payload.connection_id)
        else:
            oauth = MetaOAuthService()
            token = oauth.exchange_user_token(payload.access_token)
            row = _store_direct(db, current_user, token, oauth.verify_permissions(token["access_token"]), payload.connection_id)
        db.commit()
        return {"credential_id": row.credential_id, "connection_id": row.id, "expires_in": 600}
    except (MetaOAuthError, FBConnectorError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/authorize-first")
@router.get("/authorize")
def authorize_meta(request: Request, meta_account_id: str | None = Query(None), return_to: str | None = Query(None),
                   connection_id: str | None = Query(None), db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    if connection_id:
        owned_connection(db, current_user, connection_id=connection_id)
    if meta_account_id and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="个人接入请使用我的 Meta 授权入口")
    state = _new_oauth_state(current_user, effective_tenant_id(current_user), meta_account_id,
                            _oauth_return_to(request, return_to), db=db, connection_id=connection_id)
    try:
        url = FBConnectorClient().authorize(state).get("authorization_url") if settings.FB_ACCESS_MODE == "connector" else MetaOAuthService().authorization_url(state)
        if not url:
            raise MetaOAuthError("Meta 未返回授权地址")
    except (MetaOAuthError, FBConnectorError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url, "expires_in": 600, "oauth_mode": "discover_businesses"}


@router.post("/claim")
def claim_oauth(payload: OAuthClaimRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    if settings.FB_ACCESS_MODE != "connector" or not settings.FB_CONNECTOR_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="Connector 回调签名未配置")
    try:
        receipt = jwt.decode(payload.receipt, settings.FB_CONNECTOR_SIGNING_KEY, algorithms=["HS256"],
                             audience="saas-meta-oauth", options={"require": ["exp", "state_hash", "credential_id"]})
        if receipt["state_hash"] != sha256(payload.state.encode()).hexdigest():
            raise jwt.InvalidTokenError()
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="海外授权回执无效，请重新发起授权") from exc
    try:
        _, connection_id = _consume_state(db, payload.state, current_user)
        result = FBConnectorClient().credential_health([receipt["credential_id"]]).get("items", [])
        verified = next((x for x in result if x.get("id") == receipt["credential_id"]), None)
        if not verified or verified.get("status") != "ACTIVE":
            raise HTTPException(status_code=400, detail="海外个人授权已失效")
        row = bind_connection(db, current_user, {**verified, "credential_id": receipt["credential_id"],
                    "data_access_expires_at": receipt.get("data_access_expires_at")}, mode="connector", expected_connection_id=connection_id)
        db.commit()
        return {"credential_id": row.credential_id, "connection_id": row.id}
    except (HTTPException, FBConnectorError) as exc:
        db.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/callback")
def meta_oauth_callback(state: str = Query(...), code: str | None = Query(None), error: str | None = Query(None),
                        error_description: str | None = Query(None), db: Session = Depends(get_db)):
    if settings.FB_ACCESS_MODE == "connector":
        return _frontend_redirect(meta_auth="error", message="OAuth 回调必须由海外 Connector 处理")
    try:
        payload, connection_id = _consume_state(db, state)
        with tenant_scope(payload["tid"]):
            user = db.query(User).filter_by(id=payload["sub"], tenant_id=payload["tid"]).first()
            if not user or not user.is_active:
                raise HTTPException(status_code=403, detail="发起授权的用户已失效")
            if error or not code:
                db.commit()
                return _frontend_redirect(meta_auth="error", message=error_description or error or "用户取消授权")
            oauth = MetaOAuthService()
            token = oauth.exchange_code(code)
            row = _store_direct(db, user, token, oauth.verify_permissions(token["access_token"]), connection_id)
            db.commit()
            return _frontend_redirect(meta_auth="businesses", credential_id=row.credential_id)
    except (HTTPException, MetaOAuthError) as exc:
        db.rollback()
        return _frontend_redirect(meta_auth="error", message=str(getattr(exc, "detail", exc))[:240])


def _remote_accounts(db, user, credential_id):
    connection = owned_connection(db, user, credential_id=credential_id, active=True)
    if connection.access_mode == "connector":
        rows = FBConnectorClient().oauth_ad_accounts(credential_id).get("accounts", [])
    else:
        cred = db.query(Credential).filter_by(id=credential_id, connection_id=connection.id, status="ACTIVE").first()
        if not cred or cred.is_expired():
            raise HTTPException(status_code=400, detail="个人 OAuth 凭据已失效")
        rows = MetaOAuthService().get_ad_accounts(cred.get_access_token())
    return connection, rows


@router.get("/businesses")
def oauth_businesses(credential_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    connection = owned_connection(db, current_user, credential_id=credential_id, active=True)
    try:
        if connection.access_mode == "connector":
            return FBConnectorClient().oauth_businesses(credential_id)
        cred = db.query(Credential).filter_by(id=credential_id).one()
        return {"credential_id": credential_id, "businesses": MetaOAuthService().get_businesses(cred.get_access_token())}
    except (MetaOAuthError, FBConnectorError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ad-accounts")
def oauth_ad_accounts(credential_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    try:
        _, rows = _remote_accounts(db, current_user, credential_id)
        return {"credential_id": credential_id, "accounts": rows}
    except (MetaOAuthError, FBConnectorError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/complete-accounts")
def oauth_complete_accounts(payload: OAuthAccountsCompleteRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    from services.meta_connection_sync import import_connection_accounts, sync_connection_pages
    try:
        connection, rows = _remote_accounts(db, current_user, payload.credential_id)
        selected = [x for x in rows if str(x.get("id")) in set(payload.account_ids)]
        if len({str(x.get("id")) for x in selected}) != len(set(payload.account_ids)):
            raise HTTPException(status_code=400, detail="所选广告账户不在当前授权范围内")
        imported = import_connection_accounts(db, connection, current_user, selected)
        db.commit()
        try:
            page_sync = {"status": "SUCCESS", **sync_connection_pages(db, connection)}
        except (MetaOAuthError, FBConnectorError) as exc:
            db.rollback()
            page_sync = {"status": "FAILED", "count": 0, "error": str(exc)}
        try:
            from tasks.meta_sync_tasks import sync_personal_connection_task
            sync_personal_connection_task.delay(connection.id, requested_by=current_user.id)
        except Exception:
            from core.logger import logger
            logger.warning("[meta-auth] personal asset sync queue unavailable, connection=%s", connection.id)
        return {"success": True, "connection_id": connection.id, "accounts": imported, "page_sync": page_sync}
    except (MetaOAuthError, FBConnectorError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/complete")
def oauth_complete(payload: OAuthCompleteRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    _, rows = _remote_accounts(db, current_user, payload.credential_id)
    ids = [str(x["id"]) for x in rows if str((x.get("business") or {}).get("id")) == payload.business_id]
    if not ids:
        raise HTTPException(status_code=400, detail="当前个人授权不能访问所选 BM 的广告账户")
    return oauth_complete_accounts(OAuthAccountsCompleteRequest(credential_id=payload.credential_id, account_ids=ids), db, current_user)
