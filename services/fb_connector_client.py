"""国内 SaaS 调用海外 FB Connector 的统一客户端。"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import requests

from config.settings import settings
from core.logger import logger
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
        timeout: int | float | None = None,
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
        started = time.monotonic()
        logger.info(
            "[FBConnector] request start request_id=%s method=%s path=%s idempotent=%s",
            rid,
            method.upper(),
            path,
            bool(idempotency_key),
        )
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
                timeout=timeout if timeout is not None else settings.FB_CONNECTOR_TIMEOUT,
            )
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            remote_request_id = getattr(response, "headers", {}).get("X-Request-Id")
            logger.info(
                "[FBConnector] response request_id=%s remote_request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
                rid,
                remote_request_id,
                method.upper(),
                path,
                response.status_code,
                elapsed_ms,
            )
            try:
                result = response.json()
            except ValueError:
                result = {"detail": response.text[:500]}
            if response.status_code >= 400:
                detail = result.get("detail", "FB Connector 请求失败") if isinstance(result, dict) else "FB Connector 请求失败"
                logger.warning(
                    "[FBConnector] request failed request_id=%s method=%s path=%s status=%s detail=%s",
                    rid,
                    method.upper(),
                    path,
                    response.status_code,
                    str(detail)[:300],
                )
                raise FBConnectorError(str(detail), status_code=response.status_code, request_id=rid)
            return result if isinstance(result, dict) else {"data": result}
        except FBConnectorError:
            raise
        except requests.RequestException as exc:
            logger.exception(
                "[FBConnector] transport error request_id=%s method=%s path=%s elapsed_ms=%s",
                rid,
                method.upper(),
                path,
                round((time.monotonic() - started) * 1000, 1),
            )
            raise FBConnectorError(f"FB Connector 不可用: {exc}", request_id=rid) from exc

    def authorize(self, state: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/authorize", {"state": state}, request_id=request_id)

    def sdk_config(self, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/internal/meta/oauth/sdk-config", {}, request_id=request_id)

    def sdk_login(self, access_token: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/sdk-login", {"access_token": access_token}, request_id=request_id)

    def oauth_businesses(self, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/businesses", {"credential_id": credential_id}, request_id=request_id)

    def oauth_ad_accounts(self, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/ad-accounts", {"credential_id": credential_id}, request_id=request_id)

    def oauth_complete(self, credential_id: str, business_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/oauth/complete", {"credential_id": credential_id, "business_id": business_id}, request_id=request_id)

    def verify_business(self, business_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/business/verify", {"business_id": business_id, "credential_id": credential_id}, request_id=request_id)

    def verify_account(self, business_id: str, account_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/business/verify-account", {"business_id": business_id, "account_id": account_id, "credential_id": credential_id}, request_id=request_id)

    def sync_accounts(self, business_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/accounts/sync", {"business_id": business_id, "credential_id": credential_id}, request_id=request_id)

    def sync_pages(self, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/internal/meta/pages/sync", {"credential_id": credential_id}, request_id=request_id)

    def list_custom_audiences(self, account_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        """读取账户级 Custom Audience 元数据；Connector 端不得返回成员数据。"""
        return self._request(
            "POST",
            "/internal/meta/audiences/list",
            {"account_id": account_id, "credential_id": credential_id},
            request_id=request_id,
        )

    def list_tracking_assets(self, account_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        """读取 Pixel / Dataset 元数据，不返回事件或用户数据。"""
        return self._request(
            "POST",
            "/internal/meta/tracking-assets/list",
            {"account_id": account_id, "credential_id": credential_id},
            request_id=request_id,
        )

    def upload_media(self, media_id: str, credential_id: str, account_id: str, asset_type: str, source_url: str, *, cover_url: str | None = None, expected_md5: str | None = None, expected_sha256: str | None = None, request_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if not idempotency_key:
            raise FBConnectorError("素材上传必须提供幂等键")
        payload = {"media_id": media_id, "credential_id": credential_id, "account_id": account_id, "asset_type": asset_type, "source_url": source_url, "idempotency_key": idempotency_key}
        if expected_md5:
            payload["expected_md5"] = expected_md5.lower()
        if expected_sha256:
            payload["expected_sha256"] = expected_sha256.lower()
        if cover_url:
            payload["cover_url"] = cover_url
        return self._request("POST", "/internal/meta/media/upload", payload, request_id=request_id, idempotency_key=idempotency_key)

    def media_upload_status(self, task_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/internal/meta/media/upload/{task_id}", {}, request_id=request_id)

    def create_campaign(
        self,
        task_id: str,
        credential_id: str,
        account_id: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """创建 Campaign，所有调用方必须显式提供凭据和广告账户。"""
        if not idempotency_key:
            raise FBConnectorError("投放创建必须提供幂等键")
        request_payload = {
            "task_id": task_id,
            "credential_id": credential_id,
            "account_id": account_id,
            "payload": payload,
            "idempotency_key": idempotency_key,
        }
        return self._request(
            "POST",
            "/internal/meta/campaigns/create",
            request_payload,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def deploy_campaign(self, payload: dict[str, Any], *, request_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if not idempotency_key:
            raise FBConnectorError("完整投放创建必须提供幂等键")
        return self._request("POST", "/internal/meta/campaigns/deploy", payload, request_id=request_id, idempotency_key=idempotency_key)

    def deploy_status(self, connector_task_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/internal/meta/campaigns/create/{connector_task_id}", {}, request_id=request_id)

    def list_campaigns(self, account_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/meta/campaigns/list",
            {"account_id": account_id, "credential_id": credential_id},
            request_id=request_id,
            timeout=settings.FB_CONNECTOR_REPORT_TIMEOUT,
        )

    def pause_campaign(self, campaign_id: str, credential_id: str, *, request_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if not idempotency_key:
            raise FBConnectorError("暂停广告必须提供幂等键")
        return self._request("POST", "/internal/meta/campaigns/pause", {"campaign_id": campaign_id, "credential_id": credential_id, "idempotency_key": idempotency_key}, request_id=request_id, idempotency_key=idempotency_key)

    def list_adsets(self, campaign_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/meta/campaigns/adsets",
            {"parent_id": campaign_id, "credential_id": credential_id},
            request_id=request_id,
            timeout=settings.FB_CONNECTOR_REPORT_TIMEOUT,
        )

    def list_ads(self, adset_id: str, credential_id: str, *, request_id: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/meta/campaigns/ads",
            {"parent_id": adset_id, "credential_id": credential_id},
            request_id=request_id,
            timeout=settings.FB_CONNECTOR_REPORT_TIMEOUT,
        )

    def update_object(
        self,
        object_type: str,
        object_id: str,
        credential_id: str,
        fields: dict[str, Any],
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not fields:
            raise FBConnectorError("投放对象更新字段不能为空")
        return self._request(
            "POST",
            "/internal/meta/campaigns/update-object",
            {
                "object_type": object_type,
                "object_id": object_id,
                "credential_id": credential_id,
                "fields": fields,
                "idempotency_key": idempotency_key,
            },
            request_id=request_id,
            idempotency_key=idempotency_key,
        )

    def cleanup_deployment(
        self,
        connector_task_id: str,
        credential_id: str,
        *,
        orphaned_only: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/internal/meta/campaigns/cleanup",
            {
                "connector_task_id": connector_task_id,
                "credential_id": credential_id,
                "orphaned_only": orphaned_only,
            },
            request_id=request_id,
        )

    def get_insights(self, account_id: str, credential_id: str, days: int = 30, *, level: str = "account", since: str | None = None, until: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"account_id": account_id, "credential_id": credential_id, "days": days, "level": level}
        if since and until:
            payload.update({"since": since, "until": until})
        return self._request(
            "POST",
            "/internal/meta/reports/insights",
            payload,
            request_id=request_id,
            timeout=settings.FB_CONNECTOR_REPORT_TIMEOUT,
        )
