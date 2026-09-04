"""Meta OAuth 授权入口：把用户授权的 Token 安全绑定到指定 BM。"""
from datetime import datetime, timedelta
from urllib.parse import urlencode
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config.settings import settings
from core.auth import require_admin
from core.database import get_db
from core.enums import CredentialSource
from core.logger import logger
from core.tenant import tenant_scope
from models import MetaAccount, User
from models.tenant import UserRole
from services.credential_service import CredentialService
from services.meta.oauth_service import MetaOAuthError, MetaOAuthService
from tasks.meta_sync_tasks import sync_ad_accounts_task

router = APIRouter(prefix="/api/v1/meta-auth", tags=["Meta OAuth 授权"])


def _frontend_redirect(**params: str) -> RedirectResponse:
    base = settings.FRONTEND_BASE_URL.rstrip("/") + "/admin/credentials"
    return RedirectResponse(f"{base}?{urlencode(params)}", status_code=302)


@router.get("/authorize")
def authorize_meta(
    meta_account_id: str = Query(..., description="要绑定授权的 BM 主键"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # 平台账号（tenant_id 为空）不能发起授权：回调时创建凭据需要租户上下文，
    # 缺少它会在写入阶段失败。这里提前拒绝，好过让用户在 Meta 授权后才发现。
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="平台账号不属于任何租户，无法发起 Meta 授权；请切换到目标租户后重试",
        )

    meta = db.query(MetaAccount).filter(MetaAccount.id == meta_account_id).first()
    if not meta:
        raise HTTPException(status_code=404, detail="BM 不存在")
    now = datetime.utcnow()
    state = jwt.encode({
        "purpose": "meta_oauth",
        "sub": current_user.id,
        "tid": tenant_id,
        "meta_account_id": meta.id,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }, settings.SECRET_KEY, algorithm="HS256")
    try:
        url = MetaOAuthService().authorization_url(state)
    except MetaOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"authorization_url": url, "expires_in": 600}


@router.get("/callback", include_in_schema=True)
def meta_oauth_callback(
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if error or not code:
        return _frontend_redirect(meta_auth="error", message=error_description or error or "用户取消授权")
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("purpose") != "meta_oauth":
            raise jwt.InvalidTokenError("state purpose 不匹配")
    except jwt.PyJWTError:
        return _frontend_redirect(meta_auth="error", message="授权 state 无效或已过期")

    # 回调没有本系统 Bearer Token，必须从签名 state 恢复租户上下文；
    # tenant_scope 确保成功、失败和提前返回时都不会把上下文泄漏给下一请求。
    with tenant_scope(payload.get("tid")):
        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if not user or not user.is_active or not UserRole.is_admin(user.role):
            return _frontend_redirect(meta_auth="error", message="发起授权的管理员已失效")
        if getattr(user, "tenant_id", None) != payload.get("tid"):
            return _frontend_redirect(meta_auth="error", message="授权租户信息已变更，请重新发起")
        meta = db.query(MetaAccount).filter(MetaAccount.id == payload.get("meta_account_id")).first()
        if not meta:
            return _frontend_redirect(meta_auth="error", message="要绑定的 BM 不存在")

        try:
            oauth = MetaOAuthService()
            token = oauth.exchange_code(code)
            scopes = oauth.verify_permissions(token["access_token"])
            business = oauth.verify_business_access(token["access_token"], meta.business_id)
            cred = CredentialService(db).create_for_meta(
                meta_account_id=meta.id,
                plain_token=token["access_token"],
                token_type="USER",
                expires_at=token["expires_at"],
                replace_active=True,
                # 溯源：谁在什么权限范围下授的权
                source=CredentialSource.OAUTH.value,
                scopes=scopes,
                granted_by_user_id=user.id,
                meta_user_id=token.get("meta_user_id"),
            )
            cred.name = f"Meta OAuth - {business.get('name') or meta.name}"
            cred.app_id = settings.FB_APP_ID
            cred.last_verified_at = datetime.utcnow()
            db.commit()
        except (MetaOAuthError, PermissionError) as exc:
            # PermissionError：租户上下文缺失导致写入被拒（core.tenant 守卫）。
            # 前端回调页只认重定向 + meta_auth=error，不能抛 JSON，否则页面逻辑失效。
            return _frontend_redirect(meta_auth="error", message=str(exc)[:240])

        # 授权成功即拉取该 BM 下的广告账户：用户完成 OAuth 后不必再手工导入一遍。
        # 走异步任务，避免在浏览器跳转链路上同步等待 Meta API。
        try:
            sync_ad_accounts_task.delay(meta.id)
        except Exception as exc:  # 同步投递失败不影响授权结果
            logger.warning(f"[meta-auth] BM {meta.id} 自动同步任务投递失败: {exc}")

        return _frontend_redirect(meta_auth="success", meta_account_id=meta.id)
