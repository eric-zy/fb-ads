"""Meta OAuth 2.0 授权流程。

支持两种入口：已有 BM 重新授权；或 OAuth-first 先登录 Meta、发现 BM、选择 BM 后完成接入。
Access Token 只进入 credentials 加密字段，前端只拿短时 credential_id。
"""
from datetime import datetime, timedelta
from urllib.parse import urlencode
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from config.settings import settings
from core.auth import require_admin
from core.database import get_db
from core.enums import CredentialSource, CredentialStatus
from core.logger import logger
from core.tenant import tenant_scope
from models import AdAccount, Credential, MetaAccount, MetaConnection, User
from models.ad_account import SystemStatus
from models.tenant import UserRole
from services.credential_service import CredentialService, CredentialError
from services.meta.oauth_service import MetaOAuthError, MetaOAuthService
from tasks.meta_sync_tasks import sync_meta_authorization_task, sync_ad_accounts_task, sync_meta_pages_task

router = APIRouter(prefix="/api/v1/meta-auth", tags=["Meta OAuth 授权"])

class OAuthCompleteRequest(BaseModel):
    credential_id: str = Field(..., description="本次 OAuth 产生的临时凭据 ID")
    business_id: str = Field(..., description="用户选择的 Meta Business ID")

class OAuthAccountsCompleteRequest(BaseModel):
    credential_id: str = Field(..., description="本次 OAuth 产生的临时凭据 ID")
    account_ids: list[str] = Field(..., min_length=1, description="用户选择的 Meta 广告账户 ID")

class SDKLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=20)

@router.get("/sdk-config")
def sdk_config(_: User = Depends(require_admin)):
    """返回可公开给浏览器 SDK 的 App ID；绝不返回 App Secret。"""
    if not settings.FB_APP_ID:
        raise HTTPException(status_code=503, detail="Meta App ID 未配置")
    return {"app_id": settings.FB_APP_ID, "version": settings.FB_API_VERSION}

@router.post("/sdk-login")
def sdk_login(payload: SDKLoginRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """接收 FB.login 返回的短期 Token，在服务端验证并创建临时凭据。"""
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="平台账号不属于任何租户，无法接入 Meta 广告账号")
    try:
        oauth = MetaOAuthService()
        token = oauth.exchange_user_token(payload.access_token)
        scopes = oauth.verify_permissions(token["access_token"])
        existing = db.query(Credential).filter(Credential.tenant_id == tenant_id, Credential.source == CredentialSource.OAUTH.value, Credential.status == CredentialStatus.ACTIVE.value, Credential.meta_user_id == str(token.get("meta_user_id"))).order_by(Credential.updated_at.desc()).first() if token.get("meta_user_id") else None
        pending = db.query(MetaAccount).filter(MetaAccount.id == existing.meta_account_id).first() if existing else None
        if not pending or not (pending.business_id or "").startswith("__oauth_pending__"):
            pending_id = str(uuid.uuid4()); pending = MetaAccount(id=pending_id, name="Meta SDK 待绑定", business_id=f"__oauth_pending__{pending_id}", app_id=settings.FB_APP_ID, status="ARCHIVED", sync_status="PENDING", description="JavaScript SDK 登录临时授权容器")
            db.add(pending); db.flush()
        cred = _upsert_oauth_credential(db, meta_account_id=pending.id, token=token, scopes=scopes, user=current_user, name="Meta SDK OAuth - 待选择广告账户")
        db.commit()
        return {"credential_id": cred.id, "expires_in": 600}
    except (MetaOAuthError, CredentialError) as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc

def _frontend_redirect(path: str = "/dashboard/accounts", **params: str) -> RedirectResponse:
    base = settings.FRONTEND_BASE_URL.rstrip("/") + path
    return RedirectResponse(f"{base}?{urlencode(params)}", status_code=302)

def _new_oauth_state(user: User, tenant_id: str, meta_account_id: str | None = None) -> str:
    now = datetime.utcnow()
    payload = {"purpose":"meta_oauth","sub":user.id,"tid":tenant_id,"jti":uuid.uuid4().hex,"iat":now,"exp":now+timedelta(minutes=10)}
    if meta_account_id: payload["meta_account_id"] = meta_account_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _upsert_oauth_credential(
    db: Session, *, meta_account_id: str, token: dict, scopes: list,
    user: User, name: str,
) -> Credential:
    """同一 Meta 用户对同一目标只保留一条有效 OAuth 凭据。"""
    meta_user_id = token.get("meta_user_id")
    connection = None
    if meta_user_id:
        connection = db.query(MetaConnection).filter(
            MetaConnection.tenant_id == user.tenant_id,
            MetaConnection.meta_user_id == str(meta_user_id),
            MetaConnection.app_id == settings.FB_APP_ID,
        ).first()
        if not connection:
            connection = MetaConnection(
                id=uuid.uuid4().hex,
                tenant_id=user.tenant_id,
                meta_user_id=str(meta_user_id),
                app_id=settings.FB_APP_ID,
            )
            db.add(connection)
        connection.status = CredentialStatus.ACTIVE.value
        connection.scopes = scopes
        connection.authorized_by_user_id = user.id
        connection.expires_at = token.get("expires_at")
        connection.last_error = None
        db.flush()
    query = db.query(Credential).filter(
        Credential.tenant_id == user.tenant_id,
        Credential.meta_account_id == meta_account_id,
        Credential.source == CredentialSource.OAUTH.value,
        Credential.status == CredentialStatus.ACTIVE.value,
    )
    if meta_user_id:
        query = query.filter(Credential.meta_user_id == str(meta_user_id))
    cred = query.order_by(Credential.updated_at.desc()).first()
    if not cred:
        cred = CredentialService(db).create_for_meta(
            meta_account_id=meta_account_id,
            plain_token=token["access_token"],
            token_type="USER",
            expires_at=token["expires_at"],
            replace_active=False,
            source=CredentialSource.OAUTH.value,
            scopes=scopes,
            granted_by_user_id=user.id,
            meta_user_id=meta_user_id,
        )
    else:
        cred.set_access_token(token["access_token"])
        cred.expires_at = token["expires_at"]
        cred.scopes = scopes
        cred.granted_by_user_id = user.id
        cred.meta_user_id = meta_user_id
        cred.status = CredentialStatus.ACTIVE.value
    cred.name = name
    cred.app_id = settings.FB_APP_ID
    cred.connection_id = connection.id if connection else None
    cred.last_verified_at = datetime.utcnow()
    return cred

# 两个入口共用同一套安全逻辑：/authorize-first 明确用于“添加广告用户”，不带 BM 参数。
@router.get("/authorize-first")
@router.get("/authorize")
def authorize_meta(meta_account_id: str | None = Query(None, description="已有 BM 主键；为空表示 OAuth-first"), db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id: raise HTTPException(status_code=400, detail="平台账号不属于任何租户，无法发起 Meta 授权")
    if meta_account_id and not db.query(MetaAccount).filter(MetaAccount.id == meta_account_id).first():
        raise HTTPException(status_code=404, detail="BM 不存在")
    try:
        url = MetaOAuthService().authorization_url(_new_oauth_state(current_user, tenant_id, meta_account_id))
    except MetaOAuthError as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url, "expires_in": 600, "oauth_mode": "business" if meta_account_id else "discover_businesses"}

@router.get("/callback", include_in_schema=True)
def meta_oauth_callback(state: str = Query(...), code: str | None = Query(None), error: str | None = Query(None), error_description: str | None = Query(None), db: Session = Depends(get_db)):
    if error or not code: return _frontend_redirect(meta_auth="error", message=error_description or error or "用户取消授权")
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("purpose") != "meta_oauth" or not payload.get("sub") or not payload.get("tid"): raise jwt.InvalidTokenError("state 不合法")
    except jwt.PyJWTError: return _frontend_redirect(meta_auth="error", message="授权 state 无效或已过期")

    with tenant_scope(payload.get("tid")):
        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if not user or not user.is_active or not UserRole.is_admin(user.role): return _frontend_redirect(meta_auth="error", message="发起授权的管理员已失效")
        if getattr(user, "tenant_id", None) != payload.get("tid"): return _frontend_redirect(meta_auth="error", message="授权租户信息已变更，请重新发起")
        target_meta = None
        if payload.get("meta_account_id"):
            target_meta = db.query(MetaAccount).filter(MetaAccount.id == payload.get("meta_account_id")).first()
            if not target_meta: return _frontend_redirect(meta_auth="error", message="要绑定的 BM 不存在")
        try:
            oauth = MetaOAuthService(); token = oauth.exchange_code(code); scopes = oauth.verify_permissions(token["access_token"])
            if target_meta:
                business = oauth.verify_business_access(token["access_token"], target_meta.business_id)
                cred = _upsert_oauth_credential(db, meta_account_id=target_meta.id, token=token, scopes=scopes, user=user, name=f"Meta OAuth - {business.get('name') or target_meta.name}"); db.commit()
                try:
                    sync_meta_authorization_task.delay(cred.id)
                except Exception as exc: logger.warning(f"[meta-auth] 自动同步任务投递失败: {exc}")
                return _frontend_redirect(meta_auth="success", meta_account_id=target_meta.id)

            existing_pending_cred = db.query(Credential).filter(Credential.tenant_id == user.tenant_id, Credential.source == CredentialSource.OAUTH.value, Credential.status == CredentialStatus.ACTIVE.value, Credential.meta_user_id == str(token.get("meta_user_id"))).order_by(Credential.updated_at.desc()).first() if token.get("meta_user_id") else None
            pending = db.query(MetaAccount).filter(MetaAccount.id == existing_pending_cred.meta_account_id).first() if existing_pending_cred else None
            if not pending or not (pending.business_id or "").startswith("__oauth_pending__"):
                pending_id=str(uuid.uuid4()); pending=MetaAccount(id=pending_id,name="Meta OAuth 待绑定",business_id=f"__oauth_pending__{pending_id}",app_id=settings.FB_APP_ID,status="ARCHIVED",sync_status="PENDING",description="OAuth-first 临时授权容器，完成 BM 选择后自动转换")
                db.add(pending); db.flush()
            cred=_upsert_oauth_credential(db, meta_account_id=pending.id, token=token, scopes=scopes, user=user, name="Meta OAuth - 待选择 BM"); db.commit()
            return _frontend_redirect(meta_auth="businesses", credential_id=cred.id)
        except (MetaOAuthError, PermissionError, CredentialError) as exc:
            db.rollback(); return _frontend_redirect(meta_auth="error", message=str(exc)[:240])

@router.get("/businesses")
def oauth_businesses(credential_id: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cred=db.query(Credential).filter(Credential.id==credential_id).first()
    if not cred or cred.source!=CredentialSource.OAUTH.value: raise HTTPException(status_code=404, detail="OAuth 凭据不存在或已失效")
    if cred.granted_by_user_id!=current_user.id: raise HTTPException(status_code=403, detail="无权访问该 OAuth 授权")
    if cred.status!=CredentialStatus.ACTIVE.value or cred.is_expired(): raise HTTPException(status_code=400, detail="OAuth 凭据已失效，请重新授权")
    pending=db.query(MetaAccount).filter(MetaAccount.id==cred.meta_account_id).first() if cred.meta_account_id else None
    if not pending or not pending.business_id.startswith("__oauth_pending__"): raise HTTPException(status_code=400, detail="该 OAuth 凭据已完成 BM 绑定")
    try: businesses=MetaOAuthService().get_businesses(cred.get_access_token())
    except MetaOAuthError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"credential_id":credential_id,"businesses":businesses}

@router.get("/ad-accounts")
def oauth_ad_accounts(credential_id: str = Query(...), db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """OAuth-first 直接读取广告账户，前端无需先选择 BM。"""
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred or cred.source != CredentialSource.OAUTH.value:
        raise HTTPException(status_code=404, detail="OAuth 凭据不存在")
    if cred.granted_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该 OAuth 授权")
    if cred.status != CredentialStatus.ACTIVE.value or cred.is_expired():
        raise HTTPException(status_code=400, detail="OAuth 凭据已失效，请重新授权")
    try:
        accounts = MetaOAuthService().get_ad_accounts(cred.get_access_token())
    except MetaOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"credential_id": credential_id, "accounts": accounts}

@router.post("/complete-accounts")
def oauth_complete_accounts(payload: OAuthAccountsCompleteRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """直接接入所选广告账户；BM 由 Meta 返回值自动创建/绑定，不要求用户选择。"""
    cred = db.query(Credential).filter(Credential.id == payload.credential_id).first()
    if not cred or cred.source != CredentialSource.OAUTH.value:
        raise HTTPException(status_code=404, detail="OAuth 凭据不存在")
    if cred.granted_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权完成该 OAuth 授权")
    if cred.status != CredentialStatus.ACTIVE.value or cred.is_expired():
        raise HTTPException(status_code=400, detail="OAuth 凭据已失效，请重新授权")
    try:
        remote = MetaOAuthService().get_ad_accounts(cred.get_access_token())
        pending = db.query(MetaAccount).filter(
            MetaAccount.id == cred.meta_account_id,
            MetaAccount.business_id.like("__oauth_pending__%"),
        ).first() if cred.meta_account_id else None
        selected = {str(item.get("id")): item for item in remote if str(item.get("id")) in set(payload.account_ids)}
        if len(selected) != len(set(payload.account_ids)):
            raise MetaOAuthError("所选广告账户不在当前授权范围内")
        imported = []
        sync_credential_ids = set()
        for meta_id, item in selected.items():
            business = item.get("business") or {}
            business_id = str(business.get("id") or "").strip()
            meta = db.query(MetaAccount).filter(MetaAccount.business_id == business_id).first() if business_id else None
            if not meta and business_id:
                meta = MetaAccount(id=uuid.uuid4().hex, name=business.get("name") or f"Meta Business {business_id}", business_id=business_id, app_id=settings.FB_APP_ID, status="ACTIVE", sync_status="SUCCESS", description="OAuth 直接接入广告账号自动创建")
                meta.connection_id = cred.connection_id
                db.add(meta); db.flush()
            elif meta and cred.connection_id:
                meta.connection_id = cred.connection_id
            existing = db.query(AdAccount).filter(
                AdAccount.account_id == meta_id,
                AdAccount.business_id == (meta.id if meta else None),
                # 允许已软解绑账号重新授权恢复，避免重复创建同一 Meta 账户。
                or_(AdAccount.credential_id == (None if meta else cred.id), AdAccount.owner_type == "UNBOUND"),
            ).first()
            if not existing:
                existing = AdAccount(id=uuid.uuid4().hex, business_id=meta.id if meta else None,
                                     credential_id=None if meta else cred.id,
                                     owner_type="BUSINESS" if meta else "PERSONAL",
                                     account_id=meta_id, system_status=SystemStatus.ACTIVE.value)
                db.add(existing)
            existing.meta_business_id = business_id or None
            existing.account_name = item.get("name")
            existing.account_status = str(item.get("account_status")) if item.get("account_status") is not None else None
            # AdAccount 节点没有 effective_status；该字段只用于 Campaign/AdSet/Ad。
            existing.effective_status = None
            existing.currency = item.get("currency") or existing.currency
            existing.timezone = item.get("timezone_name") or existing.timezone
            existing.credential_id = None if meta else cred.id
            existing.connection_id = cred.connection_id
            existing.owner_type = "BUSINESS" if meta else "PERSONAL"
            existing.system_status = SystemStatus.ACTIVE.value
            existing.system_status_reason = None
            imported.append({"id": existing.id, "account_id": meta_id, "business_id": meta.id if meta else None, "business_name": meta.name if meta else None, "owner_type": existing.owner_type})
            # 一个 OAuth 连接可覆盖多个 BM。首次选中的 BM 直接复用本次凭据；
            # 其它 BM 只有在确实没有同连接凭据时才创建加密副本，避免重复授权产生孤儿记录。
            if meta:
                active = db.query(Credential).filter(
                    Credential.meta_account_id == meta.id,
                    Credential.status == CredentialStatus.ACTIVE.value,
                ).order_by(Credential.updated_at.desc()).first()
                if active and pending is not None and cred.meta_account_id == pending.id:
                    active.set_access_token(cred.get_access_token())
                    active.expires_at = cred.expires_at
                    active.scopes = cred.scopes
                    active.connection_id = cred.connection_id
                    active.last_verified_at = datetime.utcnow()
                    cred.status = CredentialStatus.DISABLED.value
                    db.delete(pending)
                    pending = None
                elif not active:
                    if pending is not None and cred.meta_account_id == pending.id:
                        cred.meta_account_id = meta.id
                        cred.name = f"Meta OAuth - {meta.name}"
                        cred.last_verified_at = datetime.utcnow()
                        db.delete(pending)
                        pending = None
                        active = cred
                    else:
                        active = CredentialService(db).create_for_meta(
                            meta_account_id=meta.id,
                            plain_token=cred.get_access_token(),
                            token_type="USER",
                            expires_at=cred.expires_at,
                            replace_active=False,
                            source=CredentialSource.OAUTH.value,
                            scopes=cred.scopes,
                            granted_by_user_id=current_user.id,
                            meta_user_id=cred.meta_user_id,
                        )
                        active.name = f"Meta OAuth - {meta.name}"
                        active.app_id = settings.FB_APP_ID
                        active.connection_id = cred.connection_id
                        active.last_verified_at = datetime.utcnow()
                sync_credential_ids.add(active.id)
            else:
                sync_credential_ids.add(cred.id)
        db.commit()
        for sync_credential_id in sync_credential_ids:
            try:
                sync_meta_authorization_task.delay(sync_credential_id)
            except Exception as exc:
                logger.warning(f"[meta-auth] 广告账户 {sync_credential_id} 自动同步任务投递失败: {exc}")
        return {"success": True, "accounts": imported}
    except (MetaOAuthError, CredentialError) as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/complete")
def oauth_complete(payload: OAuthCompleteRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    cred=db.query(Credential).filter(Credential.id==payload.credential_id).first()
    if not cred or cred.source!=CredentialSource.OAUTH.value: raise HTTPException(status_code=404, detail="OAuth 凭据不存在")
    if cred.granted_by_user_id!=current_user.id: raise HTTPException(status_code=403, detail="无权完成该 OAuth 授权")
    pending=db.query(MetaAccount).filter(MetaAccount.id==cred.meta_account_id).first() if cred.meta_account_id else None
    if not pending or not pending.business_id.startswith("__oauth_pending__"): raise HTTPException(status_code=400, detail="该 OAuth 授权已完成或已失效")
    business_id=payload.business_id.strip()
    if not business_id or business_id.startswith("__oauth_pending__"): raise HTTPException(status_code=400, detail="Business ID 无效")
    existing=db.query(MetaAccount).filter(MetaAccount.business_id==business_id, MetaAccount.id!=pending.id).first()
    try:
        token=cred.get_access_token(); business=MetaOAuthService().verify_business_access(token,business_id)
        if existing:
            for old_cred in db.query(Credential).filter(Credential.meta_account_id==existing.id, Credential.status==CredentialStatus.ACTIVE.value).all(): old_cred.status=CredentialStatus.DISABLED.value
            cred.meta_account_id=existing.id; cred.name=f"Meta OAuth - {business.get('name') or existing.name}"; existing.default_credential_id=cred.id; db.delete(pending); target=existing
        else:
            pending.name=business.get("name") or f"Meta BM {business_id}"; pending.business_id=business_id; pending.status="ACTIVE"; pending.timezone=None; pending.currency=None; pending.description="通过 Meta OAuth 2.0 接入"; cred.name=f"Meta OAuth - {pending.name}"; target=pending
        target.connection_id = cred.connection_id
        db.commit()
        try:
            sync_meta_authorization_task.delay(cred.id)
        except Exception as exc: logger.warning(f"[meta-auth] BM {target.id} 同步任务投递失败: {exc}")
        return {"success":True,"meta_account_id":target.id,"business":business}
    except (MetaOAuthError, CredentialError) as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
