"""素材上传及视频处理任务。所有 Meta 写操作均在 Worker 中执行。"""
import os
import hashlib
import shutil
import tempfile
import requests
from datetime import datetime
from celery import shared_task
from celery.exceptions import Retry
from core.database import SessionLocal
from core.logger import logger
from core.tenant import resolve_tenant_of, tenant_task
from models import CreativeAsset, MetaAssetBinding, AdAccount
from services.storage import AliyunOSSStorage
from services.media_processing import image_dimensions, video_metadata, generate_video_cover, generate_thumbnail
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from services.media_binding_service import queue_pending_asset_bindings
from config.settings import settings


@shared_task(bind=True, name="media.delete_oss_asset", max_retries=5, default_retry_delay=60)
@tenant_task(lambda self, asset_id: resolve_tenant_of(CreativeAsset, asset_id))
def delete_oss_asset_task(self, asset_id: str):
    db = SessionLocal()
    try:
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
        if not asset:
            return {"status": "deleted", "asset_id": asset_id}
        storage = AliyunOSSStorage()
        for key in {asset.object_key, asset.thumbnail_key, asset.cover_key}:
            if key:
                storage.delete(key)
        asset.storage_status = "DELETED"
        asset.deleted_at = datetime.utcnow()
        db.commit()
        return {"status": "deleted", "asset_id": asset_id}
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@shared_task(bind=True, name="media.process_oss_asset", max_retries=3, default_retry_delay=30)
@tenant_task(lambda self, asset_id: resolve_tenant_of(CreativeAsset, asset_id))
def process_oss_asset_task(self, asset_id: str, force: bool = False):
    """下载 OSS 对象到临时目录，解析元数据并生成视频封面。"""
    db = SessionLocal()
    temp_dir = tempfile.mkdtemp(prefix="media-asset-")
    try:
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
        if not asset or not asset.object_key:
            raise RuntimeError("OSS 素材不存在或缺少 object_key")
        if not force and asset.status == "READY" and asset.processing_status == "READY":
            return {"status": "ready", "asset_id": asset_id}
        asset.storage_status = "READY"
        asset.processing_status = "PROCESSING"
        asset.status = "PROCESSING"
        db.commit()
        source = os.path.join(temp_dir, asset.stored_name or "source")
        url = AliyunOSSStorage().download_url(asset.object_key)
        md5_digest = hashlib.md5()
        sha256_digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with open(source, "wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        md5_digest.update(chunk)
                        sha256_digest.update(chunk)
                        output.write(chunk)
        if asset.size is not None and os.path.getsize(source) != asset.size:
            raise RuntimeError("OSS 对象大小与素材声明不一致")
        if asset.md5 and md5_digest.hexdigest().lower() != asset.md5.lower():
            raise RuntimeError("OSS 对象 MD5 与素材记录不一致")
        if asset.sha256 and sha256_digest.hexdigest().lower() != asset.sha256.lower():
            raise RuntimeError("OSS 对象 SHA-256 与素材记录不一致")
        if asset.asset_type == "image":
            asset.width, asset.height = image_dimensions(source, asset.mime_type or "")
        else:
            asset.width, asset.height, asset.duration = video_metadata(source)
            cover = os.path.join(temp_dir, "cover.jpg")
            if generate_video_cover(source, cover):
                cover_key = f"{asset.object_key.rsplit('/', 1)[0]}/{os.path.splitext(asset.stored_name or 'source')[0]}.cover.jpg"
                AliyunOSSStorage().put_file(cover_key, cover, "image/jpeg")
                asset.cover_key = cover_key
        thumbnail = os.path.join(temp_dir, "thumbnail.jpg")
        if generate_thumbnail(source, thumbnail, asset.asset_type):
            thumbnail_key = f"{asset.object_key.rsplit('/', 1)[0]}/{os.path.splitext(asset.stored_name or 'source')[0]}.thumbnail.jpg"
            AliyunOSSStorage().put_file(thumbnail_key, thumbnail, "image/jpeg")
            asset.thumbnail_key = thumbnail_key
        if not asset.width or not asset.height:
            raise RuntimeError("无法解析素材尺寸")
        asset.processing_status = "READY"
        asset.status = "READY"
        asset.error = None
        db.commit()
        pending_bindings = db.query(MetaAssetBinding).filter(
            MetaAssetBinding.asset_id == asset.id,
            MetaAssetBinding.status == "PENDING",
            MetaAssetBinding.meta_asset_id.is_(None),
        ).all()
        queue_pending_asset_bindings(pending_bindings, db=db)
        return {"status": "ready", "asset_id": asset_id, "width": asset.width, "height": asset.height}
    except Exception as exc:
        db.rollback()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
        if asset:
            asset.processing_status = "FAILED"
            asset.status = "FAILED"
            asset.error = str(exc)[:1000]
            db.commit()
        raise self.retry(exc=exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        db.close()

@shared_task(bind=True, name="meta.upload_asset", max_retries=3, default_retry_delay=30)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def upload_asset_task(self, binding_id: str):
    db = SessionLocal()
    retries = self.request.retries
    try:
        logger.info("[MediaUpload] start binding_id=%s retry=%s", binding_id, retries)
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        account = db.query(AdAccount).filter(AdAccount.id == binding.ad_account_id).first() if binding else None
        if not binding or not asset or not account:
            raise RuntimeError("素材映射或广告账户不存在")
        if binding.status == "READY" and binding.meta_asset_id:
            return {"status": "success", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
        if asset.storage_status != "READY" or asset.processing_status != "READY" or not asset.object_key:
            binding.status = "PENDING"
            binding.error_code = "ASSET_NOT_READY"
            binding.error_message = "OSS 素材尚未完成处理，任务将稍后重试"
            db.commit()
            raise self.retry(exc=RuntimeError("OSS 素材尚未完成处理"), countdown=30)
        binding.status = "UPLOADING"
        binding.retry_count = (binding.retry_count or 0) + 1
        binding.error_message = None
        db.commit()
        ref = CredentialResolver(db).for_account(account.id)
        if ref.mode != "connector":
            raise RuntimeError("当前素材上传只支持海外 Connector")
        source_url = AliyunOSSStorage().download_url(asset.object_key)
        result = FBConnectorClient().upload_media(
            asset.id,
            ref.credential_id,
            account.account_id,
            asset.asset_type,
            source_url,
            idempotency_key=binding.id,
        )
        binding.connector_task_id = result.get("task_id")
        logger.info(
            "[MediaUpload] connector queued binding_id=%s connector_task_id=%s status=%s",
            binding_id,
            binding.connector_task_id,
            result.get("status"),
        )
        binding.status = "PROCESSING"
        binding.processing_status = "UPLOADING"
        binding.uploaded_at = datetime.utcnow()
        # 素材主表的 status 表示 OSS/本地处理状态；账户级 Meta 上传状态
        # 只写入 MetaAssetBinding，不能让一个账户的同步进度把共享素材
        # 从素材库 READY 状态变成 PROCESSING。
        db.commit()
        if not binding.connector_task_id:
            raise RuntimeError("Connector 未返回素材任务 ID")
        poll_connector_media_task.apply_async(args=[binding_id], countdown=15)
        return {"status": "queued", "binding_id": binding_id, "connector_task_id": binding.connector_task_id}
    except Exception as exc:
        db.rollback()
        if isinstance(exc, Retry):
            raise
        if binding_id:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                will_retry = retries < self.max_retries
                binding.status = "PENDING" if will_retry else "FAILED"
                binding.error_message = str(exc)[:1000]
                binding.error_code = type(exc).__name__
                db.commit()
                logger.warning(
                    "[MediaUpload] status=%s binding_id=%s retry=%s error=%s",
                    binding.status,
                    binding_id,
                    retries,
                    binding.error_message,
                )
        raise self.retry(exc=exc)
    finally:
        db.close()


@shared_task(
    bind=True,
    name="media.poll_connector_upload",
    max_retries=settings.CONNECTOR_MEDIA_POLL_MAX_RETRIES,
    default_retry_delay=15,
)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def poll_connector_media_task(self, binding_id: str):
    db = SessionLocal()
    retries = self.request.retries
    try:
        logger.info("[MediaUploadPoll] start binding_id=%s retry=%s", binding_id, retries)
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        if not binding or not binding.connector_task_id:
            return {"status": "done"}
        result = FBConnectorClient().media_upload_status(binding.connector_task_id)
        value = str(result.get("status") or "").upper()
        logger.info(
            "[MediaUploadPoll] connector status binding_id=%s connector_task_id=%s "
            "status=%s phase=%s progress=%s uploaded_bytes=%s total_bytes=%s",
            binding_id,
            binding.connector_task_id,
            value or "EMPTY",
            result.get("phase") or "",
            result.get("progress", ""),
            result.get("uploaded_bytes", ""),
            result.get("total_bytes", ""),
        )
        if value in {"SUCCESS", "READY", "COMPLETED"}:
            meta_asset_id = result.get("meta_asset_id")
            if not meta_asset_id:
                binding.status = "FAILED"
                binding.processing_status = "FAILED"
                binding.error_code = "CONNECTOR_MEDIA_ID_MISSING"
                binding.error_message = "Connector 已返回成功，但未返回 Meta 素材 ID"
                db.commit()
                logger.error(
                    "[MediaUploadPoll] success without meta_asset_id binding_id=%s connector_task_id=%s",
                    binding_id,
                    binding.connector_task_id,
                )
                return {
                    "status": "failed",
                    "binding_id": binding_id,
                    "error": binding.error_message,
                }
            binding.meta_asset_id = meta_asset_id
            binding.status = "READY"
            binding.processing_status = "READY"
            binding.last_verified_at = datetime.utcnow()
            if asset:
                asset.status = "READY"
            db.commit()
            logger.info("[MediaUploadPoll] success binding_id=%s meta_asset_id=%s", binding_id, binding.meta_asset_id)
            return {"status": "ready", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
        if value in {"FAILED", "ERROR"}:
            binding.status = "FAILED"
            binding.processing_status = "FAILED"
            binding.error_code = "CONNECTOR_MEDIA_UPLOAD"
            binding.error_message = result.get("error_message") or "Connector 素材上传失败"
            db.commit()
            logger.warning("[MediaUploadPoll] failed binding_id=%s error=%s", binding_id, binding.error_message)
            return {"status": "failed", "binding_id": binding_id, "error": binding.error_message}
        if retries >= self.max_retries:
            db.rollback()
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.processing_status = "FAILED"
                binding.error_code = "CONNECTOR_MEDIA_POLL_TIMEOUT"
                binding.error_message = f"Connector 素材任务超过最大轮询次数，最后状态: {value or 'EMPTY'}"
                db.commit()
            logger.error("[MediaUploadPoll] exhausted binding_id=%s last_status=%s", binding_id, value or "EMPTY")
            return {"status": "failed", "binding_id": binding_id, "error": "Connector 素材任务轮询超时"}
        raise self.retry(exc=RuntimeError(f"Connector 素材任务仍未完成: {value or 'EMPTY'}"))
    except Retry:
        raise
    except FBConnectorError as exc:
        db.rollback()
        if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code != 429:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.processing_status = "FAILED"
                binding.error_code = f"CONNECTOR_HTTP_{exc.status_code}"
                binding.error_message = str(exc)[:1000]
                db.commit()
                logger.warning("[MediaUploadPoll] http failed binding_id=%s status_code=%s error=%s", binding_id, exc.status_code, str(exc))
            return {"status": "failed", "binding_id": binding_id, "error": str(exc)}
        if retries >= self.max_retries:
            db.rollback()
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.processing_status = "FAILED"
                binding.error_code = f"CONNECTOR_HTTP_{exc.status_code or 'ERROR'}"
                binding.error_message = str(exc)[:1000]
                db.commit()
            logger.error("[MediaUploadPoll] retry exhausted binding_id=%s error=%s", binding_id, exc)
            return {"status": "failed", "binding_id": binding_id, "error": str(exc)}
        raise self.retry(exc=exc)
    except Exception as exc:
        db.rollback()
        if retries >= self.max_retries:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.processing_status = "FAILED"
                binding.error_code = type(exc).__name__
                binding.error_message = str(exc)[:1000]
                db.commit()
            logger.exception("[MediaUploadPoll] retry exhausted binding_id=%s", binding_id)
            return {"status": "failed", "binding_id": binding_id, "error": str(exc)}
        logger.warning("[MediaUploadPoll] retry binding_id=%s retry=%s error=%s", binding_id, retries, exc)
        raise self.retry(exc=exc)
    finally:
        db.close()
