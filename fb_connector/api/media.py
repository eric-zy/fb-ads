"""Connector 素材上传任务入口。文件内容不经过国内 API 转发。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import uuid
from fb_connector.models import ConnectorMediaTask, connector_session_factory
from core.logger import logger
from urllib.parse import urlparse
import ipaddress
import socket

router = APIRouter(prefix="/internal/meta/media", tags=["Meta Media"])

class MediaUploadRequest(BaseModel):
    media_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    asset_type: str = Field(..., pattern="^(image|video)$")
    source_url: str = Field(..., min_length=1, max_length=2048)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

@router.post("/upload", status_code=202)
async def upload_media(payload: MediaUploadRequest):
    """创建海外上传任务，实际下载和 Meta 上传由 Connector Worker 执行。"""
    parsed = urlparse(payload.source_url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="source_url 必须是 HTTP(S) 地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
        if any(ipaddress.ip_address(item[4][0]).is_private or ipaddress.ip_address(item[4][0]).is_loopback or ipaddress.ip_address(item[4][0]).is_link_local for item in addresses):
            raise HTTPException(status_code=400, detail="source_url 不允许指向内网地址")
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail="source_url 域名无法解析") from exc
    session = connector_session_factory()
    try:
        old = session.query(ConnectorMediaTask).filter(ConnectorMediaTask.idempotency_key == payload.idempotency_key).first()
        if old:
            return {"status": old.status, "task_id": old.task_id, "media_id": old.media_id, "idempotency_key": old.idempotency_key}
        task_id = uuid.uuid4().hex
        session.add(ConnectorMediaTask(task_id=task_id, media_id=payload.media_id, idempotency_key=payload.idempotency_key, status="QUEUED"))
        session.commit()
    finally:
        session.close()
    from fb_connector.tasks import upload_media_task
    try:
        async_result = upload_media_task.delay(task_id, payload.media_id, payload.credential_id, payload.account_id, payload.asset_type, payload.source_url, payload.idempotency_key)
    except Exception as exc:
        failed_session = connector_session_factory()
        try:
            row = failed_session.get(ConnectorMediaTask, task_id)
            if row:
                row.status = "FAILED"
                row.error_message = f"Worker 任务入队失败: {exc}"[:1000]
                failed_session.commit()
        finally:
            failed_session.close()
        logger.exception("[ConnectorMediaAPI] enqueue failed task_id=%s media_id=%s", task_id, payload.media_id)
        raise HTTPException(status_code=503, detail="素材上传任务暂时无法入队") from exc
    logger.info(
        "[ConnectorMediaAPI] queued task_id=%s celery_task_id=%s media_id=%s account_id=%s asset_type=%s",
        task_id,
        async_result.id,
        payload.media_id,
        payload.account_id,
        payload.asset_type,
    )
    return {"status": "QUEUED", "task_id": task_id, "media_id": payload.media_id, "idempotency_key": payload.idempotency_key}

@router.get("/upload/{task_id}")
async def upload_status(task_id: str):
    session = connector_session_factory()
    try:
        row = session.get(ConnectorMediaTask, task_id)
        if not row:
            raise HTTPException(status_code=404, detail="上传任务不存在")
        logger.info("[ConnectorMediaAPI] status task_id=%s status=%s", task_id, row.status)
        return {"task_id": row.task_id, "media_id": row.media_id, "status": row.status, "meta_asset_id": row.meta_asset_id, "error_message": row.error_message}
    finally:
        session.close()
