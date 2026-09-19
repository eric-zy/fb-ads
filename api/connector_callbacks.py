"""海外 FB Connector 回调入口。只接收脱敏状态，不接收 Access Token。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import settings
from core.database import get_db
from core.logger import logger
from models import AdAccount, CreativeAsset, MetaAccount, MetaPage
from core.tenant import bypass_tenant
from services.storage.aliyun_oss import AliyunOSSStorage
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


class MediaSourceRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=64)
    media_id: str = Field(..., min_length=1, max_length=64)

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


@router.post("/media-source")
async def media_source_callback(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
    x_request_id: str | None = Header(None),
    x_idempotency_key: str | None = Header(None),
):
    """为海外 Worker 返回最新的国内 OSS 临时下载地址。

    Connector 素材任务可能在海外 media 队列等待较久，不能复用国内
    投放入队时生成的短时签名 URL。此接口只返回指定素材的新 URL，
    不返回素材内容或凭据；请求必须通过 Connector HMAC 签名。
    """
    body = await request.body()
    headers = {
        "X-Signature": x_signature or "",
        "X-Timestamp": x_timestamp or "",
        "X-Request-Id": x_request_id or "",
        "X-Idempotency-Key": x_idempotency_key or "",
    }
    path = "/api/v1/internal/fb-connector/media-source"
    if not settings.SAAS_INTERNAL_SIGNING_KEY or not verify_request(
        settings.SAAS_INTERNAL_SIGNING_KEY,
        headers,
        "POST",
        path,
        body,
    ):
        raise HTTPException(status_code=401, detail="invalid connector signature")

    payload = MediaSourceRequest.model_validate_json(body)
    with bypass_tenant():
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == payload.media_id).first()
    if not asset or not asset.object_key:
        raise HTTPException(status_code=404, detail="素材不存在或缺少 OSS object key")
    if asset.storage_status != "READY" or asset.processing_status != "READY":
        raise HTTPException(status_code=409, detail="素材尚未完成处理")

    url = AliyunOSSStorage().download_url(asset.object_key)
    logger.info(
        "[ConnectorCallback] media source refreshed task_id=%s media_id=%s expires_in=%s",
        payload.task_id,
        payload.media_id,
        settings.OSS_DOWNLOAD_EXPIRE_SECONDS,
    )
    return {
        "task_id": payload.task_id,
        "media_id": payload.media_id,
        "url": url,
        "expires_in": settings.OSS_DOWNLOAD_EXPIRE_SECONDS,
    }
