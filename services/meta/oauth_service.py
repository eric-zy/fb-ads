"""Meta OAuth 授权服务。

只负责 OAuth 协议和 Graph API 交互；Token 的加密落库由 CredentialService 负责。
"""
from datetime import datetime, timedelta
from typing import Any, Dict
from urllib.parse import urlencode

import requests

from config.settings import settings
from core.logger import logger
from services.meta.client import MetaClient
from services.meta.errors import MetaApiError


class MetaOAuthError(Exception):
    pass


class MetaOAuthService:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    @staticmethod
    def _require_config() -> None:
        if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
            raise MetaOAuthError("Meta OAuth 未配置：请设置 FB_APP_ID 和 FB_APP_SECRET")
        if not settings.FB_OAUTH_REDIRECT_URI:
            raise MetaOAuthError("Meta OAuth 未配置回调地址 FB_OAUTH_REDIRECT_URI")

    def authorization_url(self, state: str) -> str:
        self._require_config()
        query = urlencode({
            "client_id": settings.FB_APP_ID,
            "redirect_uri": settings.FB_OAUTH_REDIRECT_URI,
            "state": state,
            "response_type": "code",
            "scope": settings.FB_OAUTH_SCOPES,
        })
        return f"https://www.facebook.com/{settings.FB_API_VERSION}/dialog/oauth?{query}"

    def _get_json(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, timeout=settings.FB_API_TIMEOUT)
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MetaOAuthError(f"Meta OAuth 请求失败: {exc}") from exc
        if response.status_code >= 400 or data.get("error"):
            error = data.get("error") or {}
            message = error.get("message") or f"HTTP {response.status_code}"
            raise MetaOAuthError(f"Meta OAuth 授权失败: {message}")
        return data

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """授权码换 Token，并尽可能升级为长期用户 Token。"""
        self._require_config()
        short = self._get_json("oauth/access_token", {
            "client_id": settings.FB_APP_ID,
            "client_secret": settings.FB_APP_SECRET,
            "redirect_uri": settings.FB_OAUTH_REDIRECT_URI,
            "code": code,
        })
        token = short.get("access_token")
        if not token:
            raise MetaOAuthError("Meta OAuth 未返回 Access Token")
        result = short
        try:
            result = self._get_json("oauth/access_token", {
                "grant_type": "fb_exchange_token",
                "client_id": settings.FB_APP_ID,
                "client_secret": settings.FB_APP_SECRET,
                "fb_exchange_token": token,
            })
        except MetaOAuthError:
            result = short
        access_token = result.get("access_token", token)
        expires_at = None
        if result.get("expires_in"):
            expires_at = datetime.utcnow() + timedelta(seconds=int(result["expires_in"]))
        meta_user_id = None
        try:
            me = self._get_json("me", {"access_token": access_token, "fields": "id,name"})
            meta_user_id = me.get("id")
        except MetaOAuthError as exc:
            logger.warning(f"[MetaOAuth] 获取授权方 Meta 用户信息失败: {exc}")
        return {
            "access_token": access_token,
            "expires_at": expires_at,
            "meta_user_id": meta_user_id,
        }

    def verify_permissions(self, access_token: str) -> list[str]:
        """确认用户实际授予了配置中的全部权限。"""
        data = self._get_json("me/permissions", {"access_token": access_token})
        granted = {
            item.get("permission")
            for item in data.get("data", [])
            if item.get("status") == "granted"
        }
        required = {
            scope.strip()
            for scope in settings.FB_OAUTH_SCOPES.split(",")
            if scope.strip()
        }
        missing = sorted(required - granted)
        if missing:
            raise MetaOAuthError(f"未授予必要的 Meta 权限: {', '.join(missing)}")
        return sorted(granted)

    def get_businesses(self, access_token: str, max_pages: int = 20) -> list[dict]:
        """读取当前 OAuth 用户可访问的 Business Manager。

        OAuth-first 接入只使用该结果做 BM 选择，不把 Token 返回给前端。
        """
        self._require_config()
        path = "me/businesses"
        params = {
            "access_token": access_token,
            "fields": "id,name,verification_status",
            "limit": 100,
        }
        businesses: list[dict] = []
        after = None
        for _ in range(max_pages):
            if after:
                params["after"] = after
            data = self._get_json(path, params)
            businesses.extend(data.get("data", []))
            after = (data.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break
        return businesses

    @staticmethod
    def verify_business_access(access_token: str, business_id: str) -> Dict[str, Any]:
        try:
            return MetaClient(access_token=access_token).get_business(business_id)
        except MetaApiError as exc:
            raise MetaOAuthError(f"授权账号无权访问该 BM: {exc}") from exc
