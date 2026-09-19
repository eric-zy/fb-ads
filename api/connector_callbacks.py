"""海外 FB Connector 回调入口。只接收脱敏状态，不接收 Access Token。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.settings import settings
from core.database import get_db
from core.logger import logger
from models import AdAccount, CampaignJobItem, CreativeAsset, MetaAccount, MetaAssetBinding, MetaPage
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


class MediaStatusCallback(BaseModel):
    event: str = Field(default="media.status", max_length=64)
    task_id: str = Field(..., min_length=1, max_length=64)
    media_id: str = Field(..., min_length=1, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)
    status: str = Field(..., min_length=1, max_length=32)
    phase: str | None = Field(default=None, max_length=32)
    meta_asset_id: str | None = Field(default=None, max_length=128)
    uploaded_bytes: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)


class DeliveryStatusCallback(BaseModel):
    event: str = Field(default="delivery.status", max_length=64)
    task_id: str = Field(..., min_length=1, max_length=64)
    source_task_id: str | None = Field(default=None, max_length=64)
    account_id: str | None = Field(default=None, max_length=64)
    status: str = Field(..., min_length=1, max_length=32)
    step: str | None = Field(default=None, max_length=32)
    campaign_id: str | None = Field(default=None, max_length=128)
    objects: dict | None = None
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1000)


def _verify_callback_signature(request: Request, path: str, body: bytes) -> None:
    """所有 Connector 状态回调统一使用原始 body 验签，避免重序列化差异。"""
    if not settings.SAAS_INTERNAL_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="SaaS 回调签名密钥未配置")
    headers = {
        "X-Signature": request.headers.get("X-Signature", ""),
        "X-Timestamp": request.headers.get("X-Timestamp", ""),
        "X-Request-Id": request.headers.get("X-Request-Id", ""),
        "X-Idempotency-Key": request.headers.get("X-Idempotency-Key", ""),
    }
    if not verify_request(settings.SAAS_INTERNAL_SIGNING_KEY, headers, "POST", path, body):
        raise HTTPException(status_code=401, detail="invalid connector signature")


@router.post("/media-status")
async def media_status_callback(request: Request, db: Session = Depends(get_db)):
    """接收海外素材状态，直接更新账户级绑定；国内轮询仅作为兜底。"""
    body = await request.body()
    path = "/api/v1/internal/fb-connector/media-status"
    _verify_callback_signature(request, path, body)
    payload = MediaStatusCallback.model_validate_json(body)
    if payload.event != "media.status":
        raise HTTPException(status_code=400, detail="invalid media callback event")
    value = payload.status.upper()
    request_id = request.headers.get("X-Request-Id")

    with bypass_tenant():
        binding = (
            db.query(MetaAssetBinding)
            .filter(MetaAssetBinding.connector_task_id == payload.task_id)
            .first()
        )
        asset = (
            db.query(CreativeAsset).filter(CreativeAsset.id == payload.media_id).first()
            if binding
            else None
        )
    if not binding:
        # 任务可能已被人工清理；签名正确时返回 200，避免 Connector 无意义重试。
        logger.warning(
            "[ConnectorCallback] media task not found task_id=%s media_id=%s request_id=%s",
            payload.task_id,
            payload.media_id,
            request_id,
        )
        return {"accepted": False, "reason": "unknown_task", "task_id": payload.task_id}
    if binding.asset_id != payload.media_id:
        logger.warning(
            "[ConnectorCallback] media task mismatch task_id=%s expected_media_id=%s actual_media_id=%s",
            payload.task_id,
            binding.asset_id,
            payload.media_id,
        )
        return {"accepted": False, "reason": "media_mismatch", "task_id": payload.task_id}

    error_code = payload.error_code or "CONNECTOR_MEDIA_UPLOAD"
    error_message = payload.error_message or "Connector 素材上传失败"
    if binding.status == "READY" and value in {"FAILED", "ERROR"}:
        return {
            "accepted": True,
            "task_id": payload.task_id,
            "media_id": payload.media_id,
            "status": binding.status,
            "meta_asset_id": binding.meta_asset_id,
            "stale": True,
            "request_id": request_id,
        }
    if value in {"SUCCESS", "READY", "COMPLETED"}:
        if not payload.meta_asset_id:
            value = "FAILED"
            error_code = payload.error_code or "CONNECTOR_MEDIA_ID_MISSING"
            error_message = payload.error_message or "Connector 成功回调缺少 Meta 素材 ID"
        else:
            binding.meta_asset_id = payload.meta_asset_id
            binding.status = "READY"
            binding.processing_status = "READY"
            binding.error_code = None
            binding.error_message = None
            binding.last_verified_at = datetime.utcnow()
            binding.uploaded_at = binding.uploaded_at or datetime.utcnow()
            if asset:
                asset.status = "READY"
    if value in {"FAILED", "ERROR"}:
        binding.status = "FAILED"
        binding.processing_status = "FAILED"
        binding.error_code = error_code
        binding.error_message = error_message
    elif value not in {"SUCCESS", "READY", "COMPLETED"}:
        # 回调乱序时不允许 READY 回退到处理中。
        if binding.status != "READY":
            binding.status = "PROCESSING"
            binding.processing_status = "UPLOADING"
            if payload.error_code:
                binding.error_code = payload.error_code
            if payload.error_message:
                binding.error_message = payload.error_message

    db.commit()
    logger.info(
        "[ConnectorCallback] media status updated task_id=%s media_id=%s status=%s binding_status=%s request_id=%s",
        payload.task_id,
        payload.media_id,
        payload.status,
        binding.status,
        request_id,
    )
    return {
        "accepted": True,
        "task_id": payload.task_id,
        "media_id": payload.media_id,
        "status": binding.status,
        "meta_asset_id": binding.meta_asset_id,
        "request_id": request_id,
    }


@router.post("/delivery-status")
async def delivery_status_callback(request: Request, db: Session = Depends(get_db)):
    """接收海外完整投放任务状态，并触发国内统一收敛逻辑。"""
    body = await request.body()
    path = "/api/v1/internal/fb-connector/delivery-status"
    _verify_callback_signature(request, path, body)
    payload = DeliveryStatusCallback.model_validate_json(body)
    if payload.event != "delivery.status":
        raise HTTPException(status_code=400, detail="invalid delivery callback event")
    value = payload.status.upper()
    request_id = request.headers.get("X-Request-Id")

    with bypass_tenant():
        item = (
            db.query(CampaignJobItem)
            .filter(CampaignJobItem.connector_task_id == payload.task_id)
            .first()
        )
        # 兼容迁移前已创建、只在 response_payload 中保存 Connector ID 的历史任务。
        if not item:
            for candidate in (
                db.query(CampaignJobItem)
                .filter(CampaignJobItem.status.in_(["PENDING", "RUNNING"]))
                .all()
            ):
                connector = (candidate.response_payload or {}).get("connector") or {}
                if connector.get("connector_task_id") == payload.task_id:
                    item = candidate
                    break
    if not item:
        logger.warning(
            "[ConnectorCallback] delivery task not found task_id=%s request_id=%s",
            payload.task_id,
            request_id,
        )
        return {"accepted": False, "reason": "unknown_task", "task_id": payload.task_id}
    with bypass_tenant():
        account = db.query(AdAccount).filter(AdAccount.id == item.ad_account_id).first()
    if payload.account_id and (not account or account.account_id != payload.account_id):
        logger.warning(
            "[ConnectorCallback] delivery account mismatch task_id=%s job_item_id=%s",
            payload.task_id,
            item.id,
        )
        return {"accepted": False, "reason": "account_mismatch", "task_id": payload.task_id}

    connector_status = payload.model_dump(exclude_none=True)
    connector_status.update(
        {
            "source": "callback",
            "received_at": datetime.utcnow().isoformat(),
            "request_id": request_id,
        }
    )
    response_payload = dict(item.response_payload or {})
    response_payload["connector_status"] = connector_status
    item.response_payload = response_payload
    if not item.connector_task_id:
        item.connector_task_id = payload.task_id
    db.commit()

    reconciled = False
    if value in {"SUCCESS", "FAILED", "ERROR"} and item.status not in {"SUCCESS", "FAILED"}:
        try:
            from tasks.campaign_tasks import poll_connector_deployment_task

            poll_connector_deployment_task.delay(item.id)
            reconciled = True
        except Exception as exc:
            # 回调已成功落库，后续定时轮询仍可兜底；不能因入队异常返回 5xx 造成重复风暴。
            logger.exception(
                "[ConnectorCallback] delivery reconcile enqueue failed task_id=%s job_item_id=%s error=%s",
                payload.task_id,
                item.id,
                exc,
            )
    logger.info(
        "[ConnectorCallback] delivery status updated task_id=%s job_item_id=%s status=%s step=%s reconciled=%s request_id=%s",
        payload.task_id,
        item.id,
        payload.status,
        payload.step or "",
        reconciled,
        request_id,
    )
    return {
        "accepted": True,
        "task_id": payload.task_id,
        "job_item_id": item.id,
        "status": payload.status,
        "reconciled": reconciled,
        "request_id": request_id,
    }

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
