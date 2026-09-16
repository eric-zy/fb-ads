"""国内 SaaS 调用海外 FB Connector 的统一客户端。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import requests

from config.settings import settings
from services.request_signer import build_signature_headers


class FBConnectorError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class FBConnectorClient:
    """所有国内到海外 FB 请求的唯一 HTTP 出口。"""

    def __init__(self, *, base_url: Optional[str] = None, signing_key: Optional[str] = None):
        if not settings.FB_CONNECTOR_ENABLED and base_url is None:
            raise FBConnectorError("FB Connector 未启用")
        self.base_url = (base_url or settings.FB_CONNECTOR_BASE_URL).rstrip("/")
        self.signing_key = signing_key or settings.FB_CONNECTOR_SIGNING_KEY
        if not self.base_url:
            raise FBConnectorError("FB Connector 地址未配置")

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        rid = request_id or uuid.uuid4().hex
        headers = build_signature_headers(
            self.signing_key,
            "saas",
            rid,
            method,
            path,
            body,
            idempotency_key or "",
        )
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {settings.CONNECTOR_SERVICE_TOKEN}"
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
                timeout=settings.FB_CONNECTOR_TIMEOUT,
            )
            try:
                result = response.json()
            except ValueError:
                result = {"detail": response.text[:500]}
            if response.status_code >= 400:
                detail = result.get("detail", "FB Connector 请求失败") if isinstance(result, dict) else "FB Connector 请求失败"
                raise FBConnectorError(str(detail), status_code=response.status_code, request_id=rid)
            return result if isinstance(result, dict) else {"data": result}
        except FBConnectorError:
            raise
        except requests.RequestException as exc:
            raise FBConnectorError(f"FB Connector 不可用: {exc}", request_id=rid) from exc

    def authorize(self, state: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/authorize", {"state": state}, request_id=request_id)

    def verify_business(self, business_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/business/verify", {"business_id": business_id, "credential_id": credential_id}, request_id=request_id)

    def verify_account(self, business_id: str, account_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/business/verify-account", {"business_id": business_id, "account_id": account_id, "credential_id": credential_id}, request_id=request_id)

    def sync_accounts(self, business_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/accounts/sync", {"business_id": business_id, "credential_id": credential_id}, request_id=request_id)

    def sync_pages(self, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/pages/sync", {"credential_id": credential_id}, request_id=request_id)

    def upload_media(self, media_id: str, credential_id: str, account_id: str, asset_type: str, source_url: str, *, request_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if not idempotency_key:
            raise FBConnectorError("素材上传必须提供幂等键")
        return self._request("POST", "/internal/meta/media/upload", {"media_id": media_id, "credential_id": credential_id, "account_id": account_id, "asset_type": asset_type, "source_url": source_url, "idempotency_key": idempotency_key}, request_id=request_id, idempotency_key=idempotency_key)

    def create_campaign(self, task_id: str, credential_id: str, account_id: str, payload: dict[str, Any], *, request_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if not idempotency_key:
            raise FBConnectorError("投放创建必须提供幂等键")
        return self._request("POST", "/internal/meta/campaigns/create", {"task_id": task_id, "credential_id": credential_id, "account_id": account_id, "payload": payload, "idempotency_key": idempotency_key}, request_id=request_id, idempotency_key=idempotency_key)

    def get_insights(self, account_id: str, days: int = 30, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/reports/insights", {"account_id": account_id, "days": days}, request_id=request_id)
