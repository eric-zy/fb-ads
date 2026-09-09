"""素材上传及视频处理任务。所有 Meta 写操作均在 Worker 中执行。"""
import os
from datetime import datetime
from celery import shared_task
from core.database import SessionLocal
from core.tenant import resolve_tenant_of, tenant_task
from models import CreativeAsset, MetaAssetBinding, AdAccount
from services.credential_service import CredentialService

@shared_task(bind=True, name="meta.upload_asset", max_retries=3, default_retry_delay=30)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def upload_asset_task(self, binding_id: str):
    db = SessionLocal()
    try:
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first() if binding else None
        account = db.query(AdAccount).filter(AdAccount.id == binding.ad_account_id).first() if binding else None
        if not binding or not asset or not account:
            raise RuntimeError("素材映射或广告账户不存在")
        if not asset.file_path or not os.path.isfile(asset.file_path):
            # 文件缺失属于不可重试错误，继续重试只会浪费 Meta API 配额并触发限流。
            binding.status = "FAILED"
            binding.error_code = "ASSET_FILE_MISSING"
            binding.error_message = f"素材文件不存在: {asset.file_path or '<empty>'}"
            asset.status = "FAILED"
            asset.error = binding.error_message
            db.commit()
            return {"status": "failed", "error_code": binding.error_code, "error": binding.error_message}
        if binding.status == "READY" and binding.meta_asset_id:
            return {"status": "success", "binding_id": binding_id, "meta_asset_id": binding.meta_asset_id}
        binding.status = "UPLOADING"
        binding.retry_count = (binding.retry_count or 0) + 1
        binding.error_message = None
        db.commit()
        service = CredentialService(db).build_service(account.id)
        result = (service.upload_video(account.account_id, asset.file_path)
                  if asset.asset_type == "video" else service.upload_image(account.account_id, asset.file_path))
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
        if binding_id:
            binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
            if binding:
                binding.status = "FAILED"
                binding.error_message = str(exc)[:1000]
                binding.error_code = type(exc).__name__
                db.commit()
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
