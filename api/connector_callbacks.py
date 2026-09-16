"""海外 FB Connector 回调入口。只接收脱敏状态，不接收 Access Token。"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from config.settings import settings
from services.request_signer import verify_request

router = APIRouter(prefix="/api/v1/internal/fb-connector", tags=["FB Connector 回调"])

class CredentialStatusCallback(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)
    status: str = Field(..., pattern="^(ACTIVE|EXPIRED|INVALID|DISABLED)$")
    meta_user_id: str | None = None
    scopes: list[str] = []
    expires_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None

@router.post("/credential-status")
async def credential_status_callback(payload: CredentialStatusCallback, x_signature: str | None = Header(None), x_timestamp: str | None = Header(None), x_request_id: str | None = Header(None), x_idempotency_key: str | None = Header(None)):
    if not settings.SAAS_INTERNAL_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="SaaS 回调签名密钥未配置")
    headers = {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or "", "X-Request-Id": x_request_id or "", "X-Idempotency-Key": x_idempotency_key or ""}
    body = payload.model_dump_json(exclude_none=True, exclude_defaults=True, by_alias=True).encode()
    if not verify_request(settings.SAAS_INTERNAL_SIGNING_KEY, headers, "POST", "/api/v1/internal/fb-connector/credential-status", body):
        raise HTTPException(status_code=401, detail="invalid connector signature")
    # T06 先完成安全接收；国内 Credential 状态映射将在 T07 数据同步阶段接入。
    return {"accepted": True, "credential_id": payload.credential_id, "request_id": x_request_id}
