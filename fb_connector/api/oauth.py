from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from pydantic import BaseModel

from services.meta.oauth_service import MetaOAuthError, MetaOAuthService


router = APIRouter(prefix="/internal/meta/oauth", tags=["Meta OAuth"])


class AuthorizeRequest(BaseModel):
    state: str

class ExchangeRequest(BaseModel):
    code: str
    scopes: list[str] = []


@router.post("/authorize")
async def authorize(payload: AuthorizeRequest):
    """生成 Meta 授权地址；state 由国内 SaaS 生成并透传，不在 Connector 重新生成。"""
    try:
        return {
            "authorization_url": MetaOAuthService().authorization_url(payload.state),
            "request_id": uuid.uuid4().hex,
            "expires_in": 600,
        }
    except MetaOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/exchange")
async def exchange(payload: ExchangeRequest):
    """在海外交换并加密保存 Token，仅返回 opaque credential_id。"""
    try:
        oauth = MetaOAuthService()
        token = oauth.exchange_code(payload.code)
        scopes = payload.scopes or oauth.verify_permissions(token["access_token"])
        from fb_connector.credential_store import DatabaseCredentialVault
        credential_id = DatabaseCredentialVault().save_oauth_result(access_token=token["access_token"], meta_user_id=token.get("meta_user_id"), expires_at=token.get("expires_at"), scopes=scopes)
        return {"credential_id": credential_id, "meta_user_id": token.get("meta_user_id"), "expires_at": token.get("expires_at")}
    except (MetaOAuthError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/callback")
async def callback(state: str = Query(...), code: str | None = Query(None), error: str | None = Query(None), error_description: str | None = Query(None)):
    """Meta 回调入口：海外交换并落库，浏览器只得到 opaque credential_id。"""
    redirect_base = __import__("os").getenv("SAAS_CALLBACK_BASE_URL", "").rstrip("/")
    if error or not code:
        return RedirectResponse(f"{redirect_base}/dashboard/meta?{urlencode({'meta_auth': 'error', 'message': error_description or error or '授权失败'})}", status_code=302)
    try:
        result = await exchange(ExchangeRequest(code=code))
        params = {"meta_auth": "success", "credential_id": result["credential_id"], "state": state}
        return RedirectResponse(f"{redirect_base}/dashboard/meta?{urlencode(params)}", status_code=302)
    except HTTPException as exc:
        return RedirectResponse(f"{redirect_base}/dashboard/meta?{urlencode({'meta_auth': 'error', 'message': str(exc.detail)[:200]})}", status_code=302)
