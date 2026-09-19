"""海外 FB Connector 回调入口。只接收脱敏状态，不接收 Access Token。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import settings
from core.database import get_db
from core.logger import logger
from models import AdAccount, MetaAccount, MetaPage
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
async def credential_status_callback(
    payload: CredentialStatusCallback,
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
    x_request_id: str | None = Header(None),
    x_idempotency_key: str | None = Header(None),
):
    if not settings.SAAS_INTERNAL_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="SaaS 回调签名密钥未配置")
    headers = {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or "", "X-Request-Id": x_request_id or "", "X-Idempotency-Key": x_idempotency_key or ""}
    # 必须使用原始请求体验签，重新序列化 Pydantic 对象可能改变字段顺序或默认字段，
    # 导致 Connector 发送的合法签名被误判。
    body = await request.body()
    if not verify_request(settings.SAAS_INTERNAL_SIGNING_KEY, headers, "POST", "/api/v1/internal/fb-connector/credential-status", body):
        raise HTTPException(status_code=401, detail="invalid connector signature")
    now = datetime.utcnow()
    page_query = db.query(MetaPage).filter(MetaPage.connector_credential_id == payload.credential_id)
    pages = page_query.all()
    for page in pages:
        page.status = payload.status
        page.last_error = payload.error_message
        if payload.status == "ACTIVE":
            page.last_synced_at = now

    businesses = db.query(MetaAccount).filter(MetaAccount.connector_credential_id == payload.credential_id).all()
    for business in businesses:
        business.sync_status = "SUCCESS" if payload.status == "ACTIVE" else "FAILED"
        business.last_synced_at = now if payload.status == "ACTIVE" else business.last_synced_at
        business.last_sync_error = payload.error_message if payload.status != "ACTIVE" else None

    accounts = db.query(AdAccount).filter(AdAccount.connector_credential_id == payload.credential_id).all()
    for account in accounts:
        capabilities = dict(account.capabilities or {})
        capabilities["connector_credential_status"] = payload.status
        if payload.error_code:
            capabilities["connector_credential_error_code"] = payload.error_code
        account.capabilities = capabilities

    db.commit()
    logger.info(
        "[ConnectorCallback] credential status updated credential_id=%s status=%s pages=%s businesses=%s accounts=%s request_id=%s",
        payload.credential_id,
        payload.status,
        len(pages),
        len(businesses),
        len(accounts),
        x_request_id,
    )
    return {
        "accepted": True,
        "credential_id": payload.credential_id,
        "request_id": x_request_id,
        "updated": {"pages": len(pages), "businesses": len(businesses), "accounts": len(accounts)},
    }
