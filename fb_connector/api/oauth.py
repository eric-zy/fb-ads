from __future__ import annotations

import uuid
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from pydantic import BaseModel, Field

from services.meta.oauth_service import MetaOAuthError, MetaOAuthService
from core.logger import logger
from fb_connector.credential_store import DatabaseCredentialVault


router = APIRouter(prefix="/internal/meta/oauth", tags=["Meta OAuth"])


def _report_oauth_auth_failure(credential_id: str, error: Exception) -> None:
    if getattr(error, "auth_failure", False):
        DatabaseCredentialVault().mark_status_and_notify(
            credential_id,
            status="INVALID",
            error_code=str(getattr(error, "code", "") or "")[:128] or None,
            error_message=str(error)[:1000],
        )


def _safe_return_base(state: str, fallback: str) -> str:
    """Only allow the two known SaaS entrypoints as OAuth return targets."""
    import base64
    import json
    try:
        payload = json.loads(base64.urlsafe_b64decode(state.split(".")[1] + "=="))
        candidate = str(payload.get("return_to", "")).rstrip("/")
    except Exception:
        candidate = ""
    return candidate if candidate in {"https://iornix.com", "http://49.232.238.163:8094"} else fallback


class AuthorizeRequest(BaseModel):
    state: str

class ExchangeRequest(BaseModel):
    code: str
    scopes: list[str] = []

class SDKLoginRequest(BaseModel):
    access_token: str = Field(..., min_length=20)

class CredentialRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)

class CompleteRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)
    business_id: str = Field(..., min_length=1, max_length=100)


@router.post("/authorize")
async def authorize(payload: AuthorizeRequest):
    """生成 Meta 授权地址；state 由国内 SaaS 生成并透传，不在 Connector 重新生成。"""
    logger.info("[ConnectorOAuth] authorize start")
    try:
        return {
            "authorization_url": MetaOAuthService().authorization_url(payload.state),
            "request_id": uuid.uuid4().hex,
            "expires_in": 600,
        }
    except MetaOAuthError as exc:
        logger.exception("[ConnectorOAuth] authorize failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/exchange")
async def exchange(payload: ExchangeRequest):
    """在海外交换并加密保存 Token，仅返回 opaque credential_id。"""
    logger.info("[ConnectorOAuth] exchange start scopes=%s", len(payload.scopes or []))
    try:
        oauth = MetaOAuthService()
        token = oauth.exchange_code(payload.code)
        scopes = payload.scopes or oauth.verify_permissions(token["access_token"])
        from fb_connector.credential_store import DatabaseCredentialVault
        credential_id = DatabaseCredentialVault().save_oauth_result(access_token=token["access_token"], meta_user_id=token.get("meta_user_id"), expires_at=token.get("expires_at"), scopes=scopes)
        return {"credential_id": credential_id, "meta_user_id": token.get("meta_user_id"), "expires_at": token.get("expires_at")}
    except (MetaOAuthError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/sdk-config")
async def sdk_config():
    from config.settings import settings
    if not settings.FB_APP_ID:
        raise HTTPException(status_code=503, detail="Meta App ID 未配置")
    return {"app_id": settings.FB_APP_ID, "version": settings.FB_API_VERSION, "login_config_id": settings.FB_LOGIN_CONFIG_ID or None}

@router.post("/sdk-login")
async def sdk_login(payload: SDKLoginRequest):
    logger.info("[ConnectorOAuth] sdk-login start")
    try:
        from config.settings import settings
        oauth = MetaOAuthService()
        token = oauth.exchange_user_token(payload.access_token)
        scopes = oauth.verify_permissions(token["access_token"])
        from fb_connector.credential_store import DatabaseCredentialVault
        credential_id = DatabaseCredentialVault().save_oauth_result(access_token=token["access_token"], meta_user_id=token.get("meta_user_id"), expires_at=token.get("expires_at"), scopes=scopes)
        return {"credential_id": credential_id, "expires_in": 600, "meta_user_id": token.get("meta_user_id")}
    except (MetaOAuthError, KeyError, ValueError) as exc:
        logger.warning("[ConnectorOAuth] sdk-login failed error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/businesses")
async def oauth_businesses(payload: CredentialRequest):
    logger.info("[ConnectorOAuth] businesses start credential_id=%s", payload.credential_id)
    try:
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        return {"credential_id": payload.credential_id, "businesses": MetaOAuthService().get_businesses(token)}
    except (MetaOAuthError, KeyError) as exc:
        _report_oauth_auth_failure(payload.credential_id, exc)
        logger.warning("[ConnectorOAuth] businesses failed credential_id=%s error=%s", payload.credential_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/ad-accounts")
async def oauth_ad_accounts(payload: CredentialRequest):
    logger.info("[ConnectorOAuth] ad-accounts start credential_id=%s", payload.credential_id)
    try:
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        return {"credential_id": payload.credential_id, "accounts": MetaOAuthService().get_ad_accounts(token)}
    except (MetaOAuthError, KeyError) as exc:
        _report_oauth_auth_failure(payload.credential_id, exc)
        logger.warning("[ConnectorOAuth] ad-accounts failed credential_id=%s error=%s", payload.credential_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/complete")
async def oauth_complete(payload: CompleteRequest):
    logger.info("[ConnectorOAuth] complete start credential_id=%s business_id=%s", payload.credential_id, payload.business_id)
    try:
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        business = MetaOAuthService().verify_business_access(token, payload.business_id.strip())
        return {"credential_id": payload.credential_id, "business": business}
    except (MetaOAuthError, KeyError, ValueError) as exc:
        _report_oauth_auth_failure(payload.credential_id, exc)
        logger.warning("[ConnectorOAuth] complete failed credential_id=%s business_id=%s error=%s", payload.credential_id, payload.business_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/callback")
async def callback(state: str = Query(...), code: str | None = Query(None), error: str | None = Query(None), error_description: str | None = Query(None)):
    """Meta 回调入口：海外交换并落库，浏览器只得到 opaque credential_id。"""
    logger.info("[ConnectorOAuth] callback received has_code=%s has_error=%s", bool(code), bool(error))
    redirect_base = __import__("os").getenv("SAAS_CALLBACK_BASE_URL", "").rstrip("/")
    redirect_base = _safe_return_base(state, redirect_base)
    if error or not code:
        return RedirectResponse(f"{redirect_base}/dashboard/accounts?{urlencode({'meta_auth': 'error', 'message': error_description or error or '授权失败'})}", status_code=302)
    try:
        result = await exchange(ExchangeRequest(code=code))
        # OAuth-first requires a second step: the domestic frontend must load
        # the Connector-visible ad accounts before the user confirms them.
        params = {"meta_auth": "businesses", "credential_id": result["credential_id"], "state": state}
        return RedirectResponse(f"{redirect_base}/dashboard/accounts?{urlencode(params)}", status_code=302)
    except HTTPException as exc:
        return RedirectResponse(f"{redirect_base}/dashboard/accounts?{urlencode({'meta_auth': 'error', 'message': str(exc.detail)[:200]})}", status_code=302)
