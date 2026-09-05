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
from sqlalchemy.orm import Session

from config.settings import settings
from core.auth import require_admin
from core.database import get_db
from core.enums import CredentialSource, CredentialStatus
from core.logger import logger
from core.tenant import tenant_scope
from models import Credential, MetaAccount, User
from models.tenant import UserRole
from services.credential_service import CredentialService, CredentialError
from services.meta.oauth_service import MetaOAuthError, MetaOAuthService
from tasks.meta_sync_tasks import sync_ad_accounts_task

router = APIRouter(prefix="/api/v1/meta-auth", tags=["Meta OAuth 授权"])

class OAuthCompleteRequest(BaseModel):
    credential_id: str = Field(..., description="本次 OAuth 产生的临时凭据 ID")
    business_id: str = Field(..., description="用户选择的 Meta Business ID")

def _frontend_redirect(path: str = "/dashboard/accounts", **params: str) -> RedirectResponse:
    base = settings.FRONTEND_BASE_URL.rstrip("/") + path
    return RedirectResponse(f"{base}?{urlencode(params)}", status_code=302)

def _new_oauth_state(user: User, tenant_id: str, meta_account_id: str | None = None) -> str:
    now = datetime.utcnow()
    payload = {"purpose":"meta_oauth","sub":user.id,"tid":tenant_id,"jti":uuid.uuid4().hex,"iat":now,"exp":now+timedelta(minutes=10)}
    if meta_account_id: payload["meta_account_id"] = meta_account_id
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

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
                cred = CredentialService(db).create_for_meta(meta_account_id=target_meta.id, plain_token=token["access_token"], token_type="USER", expires_at=token["expires_at"], replace_active=True, source=CredentialSource.OAUTH.value, scopes=scopes, granted_by_user_id=user.id, meta_user_id=token.get("meta_user_id"))
                cred.name=f"Meta OAuth - {business.get('name') or target_meta.name}"; cred.app_id=settings.FB_APP_ID; cred.last_verified_at=datetime.utcnow(); db.commit()
                try: sync_ad_accounts_task.delay(target_meta.id)
                except Exception as exc: logger.warning(f"[meta-auth] 自动同步任务投递失败: {exc}")
                return _frontend_redirect(meta_auth="success", meta_account_id=target_meta.id)

            pending_id=str(uuid.uuid4()); pending=MetaAccount(id=pending_id,name="Meta OAuth 待绑定",business_id=f"__oauth_pending__{pending_id}",app_id=settings.FB_APP_ID,status="ARCHIVED",sync_status="PENDING",description="OAuth-first 临时授权容器，完成 BM 选择后自动转换")
            db.add(pending); db.flush()
            cred=CredentialService(db).create_for_meta(meta_account_id=pending.id,plain_token=token["access_token"],token_type="USER",expires_at=token["expires_at"],replace_active=False,source=CredentialSource.OAUTH.value,scopes=scopes,granted_by_user_id=user.id,meta_user_id=token.get("meta_user_id"))
            cred.name="Meta OAuth - 待选择 BM"; cred.app_id=settings.FB_APP_ID; cred.last_verified_at=datetime.utcnow(); db.commit()
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
            pending.name=business.get("name") or f"Meta BM {business_id}"; pending.business_id=business_id; pending.status="ACTIVE"; pending.timezone=business.get("timezone_id"); pending.currency=business.get("currency"); pending.description="通过 Meta OAuth 2.0 接入"; cred.name=f"Meta OAuth - {pending.name}"; target=pending
        db.commit()
        try: sync_ad_accounts_task.delay(target.id)
        except Exception as exc: logger.warning(f"[meta-auth] BM {target.id} 同步任务投递失败: {exc}")
        return {"success":True,"meta_account_id":target.id,"business":business}
    except (MetaOAuthError, CredentialError) as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=str(exc)) from exc
