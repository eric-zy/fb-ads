"""Connector 素材上传任务入口。文件内容不经过国内 API 转发。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import uuid
from fb_connector.models import ConnectorMediaTask, connector_session_factory
from core.logger import logger
from config.settings import settings
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
    cover_url: str | None = Field(default=None, max_length=2048)
    expected_md5: str | None = Field(default=None, min_length=32, max_length=32, pattern=r"^[0-9a-fA-F]{32}$")
    idempotency_key: str = Field(..., min_length=8, max_length=128)


def _media_task_is_stale(row: ConnectorMediaTask, now: datetime | None = None) -> bool:
    """判断媒体任务是否已超过恢复阈值。"""
    if row.status not in {"QUEUED", "UPLOADING", "RETRY"}:
        return False
    timestamp = row.updated_at or row.created_at
    if not timestamp:
        return True
    current = now or datetime.utcnow()
    return current - timestamp >= timedelta(seconds=settings.CONNECTOR_MEDIA_STALE_SECONDS)


def _validate_remote_url(value: str | None, field_name: str) -> None:
    if not value:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是 HTTP(S) 地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None)
        if any(
            ipaddress.ip_address(item[4][0]).is_private
            or ipaddress.ip_address(item[4][0]).is_loopback
            or ipaddress.ip_address(item[4][0]).is_link_local
            for item in addresses
        ):
            raise HTTPException(status_code=400, detail=f"{field_name} 不允许指向内网地址")
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 域名无法解析") from exc

@router.post("/upload", status_code=202)
async def upload_media(payload: MediaUploadRequest):
    """创建海外上传任务，实际下载和 Meta 上传由 Connector Worker 执行。"""
    _validate_remote_url(payload.source_url, "source_url")
    _validate_remote_url(payload.cover_url, "cover_url")
    session = connector_session_factory()
    task_id = None
    requeued_stale = False
    try:
        old = (
            session.query(ConnectorMediaTask)
            .filter(ConnectorMediaTask.idempotency_key == payload.idempotency_key)
            .with_for_update()
            .first()
        )
        if old:
            if old.status == "SUCCESS" and not (
                payload.asset_type == "video" and not old.meta_thumbnail_hash
            ):
                return {"status": old.status, "task_id": old.task_id, "media_id": old.media_id, "idempotency_key": old.idempotency_key}
            # 正常的 QUEUED/UPLOADING 任务保持幂等；只有超时孤儿任务，
            # 或已明确失败的任务，才允许同一业务请求重新入队。
            thumbnail_repair = payload.asset_type == "video" and not old.meta_thumbnail_hash
            if old.status != "FAILED" and not _media_task_is_stale(old) and not thumbnail_repair:
                return {"status": old.status, "task_id": old.task_id, "media_id": old.media_id, "idempotency_key": old.idempotency_key}
            task_id = old.task_id
            old.media_id = payload.media_id
            old.credential_id = payload.credential_id
            old.account_id = payload.account_id
            old.asset_type = payload.asset_type
            old.source_url = payload.source_url
            old.cover_url = payload.cover_url
            old.expected_md5 = payload.expected_md5.lower() if payload.expected_md5 else None
            old.status = "QUEUED"
            old.meta_asset_id = None
            old.meta_thumbnail_hash = None
            old.error_message = None
            old.updated_at = datetime.utcnow()
            requeued_stale = True
        else:
            task_id = uuid.uuid4().hex
            session.add(ConnectorMediaTask(
                task_id=task_id,
                media_id=payload.media_id,
                idempotency_key=payload.idempotency_key,
                credential_id=payload.credential_id,
                account_id=payload.account_id,
                asset_type=payload.asset_type,
                source_url=payload.source_url,
                cover_url=payload.cover_url,
                expected_md5=payload.expected_md5.lower() if payload.expected_md5 else None,
                status="QUEUED",
            ))
        session.commit()
    finally:
        session.close()
    from fb_connector.tasks import upload_media_task
    try:
        async_result = upload_media_task.delay(
            task_id,
            payload.media_id,
            payload.credential_id,
            payload.account_id,
            payload.asset_type,
            payload.source_url,
            payload.idempotency_key,
            payload.expected_md5.lower() if payload.expected_md5 else None,
            payload.cover_url,
        )
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
        "[ConnectorMediaAPI] %s task_id=%s celery_task_id=%s media_id=%s account_id=%s asset_type=%s",
        "requeued stale media task" if requeued_stale else "queued",
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
        total_bytes = row.total_bytes or 0
        uploaded_bytes = row.uploaded_bytes or 0
        progress = (
            round(min(max(uploaded_bytes / total_bytes, 0), 1) * 100, 2)
            if total_bytes
            else 0
        )
        return {
            "task_id": row.task_id,
            "media_id": row.media_id,
            "status": row.status,
            "phase": row.phase,
            "total_bytes": row.total_bytes,
            "uploaded_bytes": uploaded_bytes,
            "progress": progress,
            "upload_session_id": row.upload_session_id,
            "start_offset": row.start_offset,
            "end_offset": row.end_offset,
            "meta_video_id": row.meta_video_id,
            "meta_asset_id": row.meta_asset_id,
            "meta_thumbnail_hash": row.meta_thumbnail_hash,
            "cover_url": row.cover_url,
            "expected_md5": row.expected_md5,
            "error_message": row.error_message,
        }
    finally:
        session.close()
