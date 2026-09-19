import base64
import hashlib
import json
import uuid

import requests
from cryptography.fernet import Fernet

from config.settings import settings
from core.logger import logger
from fb_connector.models import ConnectorCredential, connector_session_factory
from services.request_signer import build_signature_headers
from services.meta.errors import MetaApiError

def _cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def report_meta_auth_failure(credential_id: str, error: Exception) -> bool:
    """仅对明确的 Meta AUTH 错误更新凭据，避免网络错误误伤授权状态。"""
    if isinstance(error, MetaApiError) and error.category.value == "AUTH":
        DatabaseCredentialVault().mark_auth_failure(credential_id, error)
        return True
    return False

class DatabaseCredentialVault:
    """海外凭据仓储；对外仅返回 credential_id，不返回明文 Token。"""
    def save_oauth_result(self, *, access_token: str, meta_user_id, expires_at, scopes: list[str]) -> str:
        credential_id = uuid.uuid4().hex
        session = connector_session_factory()
        try:
            session.add(ConnectorCredential(id=credential_id, app_id=settings.FB_APP_ID,
                access_token_encrypted=_cipher().encrypt(access_token.encode()).decode(),
                token_type="USER", meta_user_id=meta_user_id, scopes=scopes, expires_at=expires_at))
            session.commit()
            return credential_id
        finally:
            session.close()

    def get_access_token(self, credential_id: str) -> str:
        session = connector_session_factory()
        try:
            row = session.get(ConnectorCredential, credential_id)
            if not row or row.status != "ACTIVE":
                raise KeyError("凭据不存在或已失效")
            return _cipher().decrypt(row.access_token_encrypted.encode()).decode()
        finally:
            session.close()

    def mark_status_and_notify(
        self,
        credential_id: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """更新 Connector 本地凭据状态，并把脱敏状态签名回调给 SaaS。

        回调是尽力而为的：凭据状态落库必须先完成，回调网络异常不能遮蔽
        原始 Meta 错误，也不能让 Celery 任务误判为成功。
        """
        session = connector_session_factory()
        payload: dict[str, object] | None = None
        try:
            row = session.get(ConnectorCredential, credential_id)
            if not row:
                logger.warning(
                    "[ConnectorCredential] status update skipped credential_id=%s reason=not_found status=%s",
                    credential_id,
                    status,
                )
                return

            row.status = status
            row.last_error = (error_message or None)[:1000] if error_message else None
            session.commit()
            payload = {
                "credential_id": row.id,
                "status": row.status,
                "meta_user_id": row.meta_user_id,
                "scopes": row.scopes or [],
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "error_code": str(error_code)[:128] if error_code else None,
                "error_message": (error_message or "")[:1000] or None,
            }
            logger.info(
                "[ConnectorCredential] local status updated credential_id=%s status=%s",
                credential_id,
                status,
            )
        except Exception:
            session.rollback()
            logger.exception(
                "[ConnectorCredential] local status update failed credential_id=%s status=%s",
                credential_id,
                status,
            )
            return
        finally:
            session.close()

        callback_base = settings.SAAS_CALLBACK_BASE_URL.rstrip("/")
        signing_key = settings.SAAS_INTERNAL_SIGNING_KEY
        if not payload or not callback_base or not signing_key:
            logger.warning(
                "[ConnectorCredential] callback skipped credential_id=%s status=%s reason=callback_not_configured",
                credential_id,
                status,
            )
            return

        path = "/api/v1/internal/fb-connector/credential-status"
        request_id = uuid.uuid4().hex
        idempotency_key = f"credential-status:{credential_id}:{status}"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = build_signature_headers(
            signing_key,
            "fb_connector",
            request_id,
            "POST",
            path,
            body,
            idempotency_key,
        )
        headers["Content-Type"] = "application/json"
        callback_url = f"{callback_base}{path}"
        try:
            logger.info(
                "[ConnectorCredential] callback start credential_id=%s status=%s request_id=%s",
                credential_id,
                status,
                request_id,
            )
            response = requests.post(
                callback_url,
                data=body,
                headers=headers,
                timeout=settings.FB_CONNECTOR_TIMEOUT,
            )
            response.raise_for_status()
            logger.info(
                "[ConnectorCredential] callback success credential_id=%s status=%s request_id=%s response_status=%s",
                credential_id,
                status,
                request_id,
                response.status_code,
            )
        except requests.RequestException:
            logger.exception(
                "[ConnectorCredential] callback failed credential_id=%s status=%s request_id=%s",
                credential_id,
                status,
                request_id,
            )

    def mark_auth_failure(self, credential_id: str, error: Exception) -> None:
        """把 Meta 鉴权失败转换为统一的 INVALID 状态回调。"""
        self.mark_status_and_notify(
            credential_id,
            status="INVALID",
            error_code=str(getattr(error, "code", "") or "")[:128] or None,
            error_message=str(error)[:1000],
        )
