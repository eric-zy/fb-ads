"""素材上传及视频处理任务。所有 Meta 写操作均在 Worker 中执行。"""
import os
import shutil
import tempfile
import requests
from datetime import datetime
from celery import shared_task
from celery.exceptions import Retry
from core.database import SessionLocal
from core.tenant import resolve_tenant_of, tenant_task
from models import CreativeAsset, MetaAssetBinding, AdAccount
from config.settings import settings
from services.storage import AliyunOSSStorage
from services.media_processing import image_dimensions, video_metadata, generate_video_cover, generate_thumbnail
from services.credential_service import CredentialService
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from services.meta import MetaApiError


@shared_task(bind=True, name="media.delete_oss_asset", max_retries=5, default_retry_delay=60)
@tenant_task(lambda self, asset_id: resolve_tenant_of(CreativeAsset, asset_id))
def delete_oss_asset_task(self, asset_id: str):
    db = SessionLocal()
    try:
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
        if not asset:
            return {"status": "deleted", "asset_id": asset_id}
        if settings.MEDIA_STORAGE_PROVIDER == "oss":
            storage = AliyunOSSStorage()
            for key in {asset.object_key, asset.thumbnail_key, asset.cover_key}:
                if key:
                    storage.delete(key)
        elif asset.file_path and os.path.isfile(asset.file_path):
            os.remove(asset.file_path)
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
        if settings.MEDIA_STORAGE_PROVIDER != "oss":
            raise RuntimeError("OSS 素材处理任务要求 MEDIA_STORAGE_PROVIDER=oss")
        source = os.path.join(temp_dir, asset.stored_name or "source")
        url = AliyunOSSStorage().download_url(asset.object_key)
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with open(source, "wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)
        if asset.size is not None and os.path.getsize(source) != asset.size:
            raise RuntimeError("OSS 对象大小与素材声明不一致")
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
        for binding in pending_bindings:
            upload_asset_task.delay(binding.id)
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
    temp_dir = tempfile.mkdtemp(prefix="meta-upload-")
    try:
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        account = db.query(AdAccount).filter(AdAccount.id == binding.ad_account_id).first() if binding else None
        if not binding or not asset or not account:
            raise RuntimeError("素材映射或广告账户不存在")
        if binding.status == "READY" and binding.meta_asset_id:
            return {"status": "success", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
        if settings.MEDIA_STORAGE_PROVIDER == "oss" and (
            asset.storage_status != "READY" or asset.processing_status != "READY" or not asset.object_key
        ):
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
        if ref.mode == "connector":
            if settings.MEDIA_STORAGE_PROVIDER != "oss" or not asset.object_key:
                raise RuntimeError("Connector 模式要求素材已存入 OSS")
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
            binding.status = "PROCESSING"
            binding.processing_status = "UPLOADING"
            binding.uploaded_at = datetime.utcnow()
            asset.status = "PROCESSING"
            db.commit()
            if binding.connector_task_id:
                poll_connector_media_task.apply_async(args=[binding_id], countdown=15)
            return {"status": "queued", "binding_id": binding_id, "connector_task_id": binding.connector_task_id}
        source_path = asset.file_path
        if settings.MEDIA_STORAGE_PROVIDER == "oss":
            source_path = os.path.join(temp_dir, asset.stored_name or "source")
            url = AliyunOSSStorage().download_url(asset.object_key)
            with requests.get(url, stream=True, timeout=300) as response:
                response.raise_for_status()
                with open(source_path, "wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
            if asset.size is not None and os.path.getsize(source_path) != asset.size:
                raise RuntimeError("OSS 对象大小与素材记录不一致")
        if not source_path or not os.path.isfile(source_path):
            binding.status = "FAILED"
            binding.error_code = "ASSET_FILE_MISSING"
            binding.error_message = f"素材文件不存在: {source_path or '<empty>'}"
            asset.status = "FAILED"
            asset.error = binding.error_message
            db.commit()
            return {"status": "failed", "error_code": binding.error_code, "error": binding.error_message}
        service = CredentialService(db).build_service(account.id)
        result = (service.upload_video(account.account_id, source_path)
                  if asset.asset_type == "video" else service.upload_image(account.account_id, source_path))
        binding.meta_asset_id = result.get("video_id") if asset.asset_type == "video" else result.get("hash")
        if not binding.meta_asset_id:
            raise RuntimeError("Meta 未返回素材 ID")
        binding.uploaded_at = datetime.utcnow()
        binding.processing_status = "UPLOADING" if asset.asset_type == "video" else "READY"
        binding.status = "PROCESSING" if asset.asset_type == "video" else "READY"
        asset.status = "PROCESSING" if asset.asset_type == "video" else "READY"
        db.commit()
        if asset.asset_type == "video":
            poll_video_ready_task.apply_async(args=[binding_id], countdown=15)
        return {"status": "success", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
    except Exception as exc:
        db.rollback()
        if isinstance(exc, Retry):
            raise
        if binding_id:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.error_message = str(exc)[:1000]
                binding.error_code = (
                    f"META_{exc.category.value}" if isinstance(exc, MetaApiError)
                    else type(exc).__name__
                )
                db.commit()
        # Meta 权限、对象不存在和参数校验错误不会因重试恢复，避免持续消耗队列/API 配额。
        if isinstance(exc, MetaApiError) and not exc.retryable:
            return {
                "status": "failed",
                "binding_id": binding_id,
                "error_code": f"META_{exc.category.value}",
                "error": str(exc),
            }
        raise self.retry(exc=exc)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        db.close()


@shared_task(bind=True, name="media.poll_connector_upload", max_retries=20, default_retry_delay=15)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def poll_connector_media_task(self, binding_id: str):
    db = SessionLocal()
    try:
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        if not binding or not binding.connector_task_id:
            return {"status": "done"}
        result = FBConnectorClient().media_upload_status(binding.connector_task_id)
        value = str(result.get("status") or "").upper()
        if value in {"SUCCESS", "READY", "COMPLETED"}:
            binding.meta_asset_id = result.get("meta_asset_id")
            binding.status = "READY"
            binding.processing_status = "READY"
            binding.last_verified_at = datetime.utcnow()
            if asset:
                asset.status = "READY"
            db.commit()
            return {"status": "ready", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
        if value in {"FAILED", "ERROR"}:
            binding.status = "FAILED"
            binding.processing_status = "FAILED"
            binding.error_code = "CONNECTOR_MEDIA_UPLOAD"
            binding.error_message = result.get("error_message") or "Connector 素材上传失败"
            db.commit()
            return {"status": "failed", "binding_id": binding_id, "error": binding.error_message}
        raise self.retry()
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
            return {"status": "failed", "binding_id": binding_id, "error": str(exc)}
        raise self.retry(exc=exc)
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()

@shared_task(bind=True, name="meta.poll_video_ready", max_retries=20, default_retry_delay=15)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def poll_video_ready_task(self, binding_id: str):
    db = SessionLocal()
    try:
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        account = db.query(AdAccount).filter(AdAccount.id == binding.ad_account_id).first() if binding else None
        if not binding or binding.status != "PROCESSING":
            return {"status": "done"}
        service = CredentialService(db).build_service(account.id)
        result = service.client._get(binding.meta_asset_id, {"fields": "status"})
        status = result.get("status") or {}
        value = status.get("video_status") or status.get("processing_phase") or status.get("status")
        if str(value).upper() in {"READY", "PUBLISHED", "COMPLETED"}:
            binding.status = "READY"; binding.processing_status = "READY"; binding.last_verified_at = datetime.utcnow(); asset.status = "READY"
            db.commit(); return {"status": "ready"}
        if str(value).upper() in {"ERROR", "FAILED"}:
            raise RuntimeError(f"Meta 视频处理失败: {status}")
        db.commit()
        raise self.retry()
    except Exception as exc:
        db.rollback()
        if "Retry" not in type(exc).__name__:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"; binding.error_message = str(exc)[:1000]; db.commit()
        raise
    finally:
        db.close()
