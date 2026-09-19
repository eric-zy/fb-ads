"""恢复 Worker 重启或强制终止后遗留的国内异步任务。"""

from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import or_

from config.settings import settings
from core.database import SessionLocal
from core.enums import JobItemStatus
from core.logger import logger
from core.tenant import bypass_tenant
from models import CampaignJobItem, CreativeAsset, MetaAssetBinding


def _cutoff() -> datetime:
    return datetime.utcnow() - timedelta(seconds=settings.ASYNC_TASK_STALE_SECONDS)


@shared_task(name="maintenance.recover_stale_domestic_work")
def recover_stale_domestic_work(limit: int = 100):
    """回收素材处理、账户素材绑定和投放子项的孤儿状态并重新入队。"""
    db = SessionLocal()
    result = {"assets": 0, "bindings": 0, "job_items": 0, "failed": 0}
    try:
        # 这是系统级巡检，必须显式绕过租户过滤；重新投递的业务任务会自行解析租户。
        with bypass_tenant():
            asset_rows = (
                db.query(CreativeAsset)
                .filter(
                    CreativeAsset.processing_status == "PROCESSING",
                    CreativeAsset.updated_at < _cutoff(),
                    CreativeAsset.status != "ARCHIVED",
                )
                .order_by(CreativeAsset.updated_at.asc())
                .limit(limit)
                .all()
            )
            for asset in asset_rows:
                asset_id = asset.id
                asset.processing_status = "PENDING"
                asset.status = "PENDING"
                asset.retry_count = (asset.retry_count or 0) + 1
                asset.error = "检测到素材处理任务超时，已自动重新入队"
                db.commit()
                try:
                    from tasks.media_tasks import process_oss_asset_task

                    process_oss_asset_task.delay(asset_id)
                    result["assets"] += 1
                    logger.warning("[Recovery] requeued stale asset asset_id=%s", asset_id)
                except Exception as exc:
                    db.rollback()
                    asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
                    if asset:
                        asset.processing_status = "FAILED"
                        asset.status = "FAILED"
                        asset.error = f"恢复素材处理任务入队失败: {exc}"[:1000]
                        db.commit()
                    result["failed"] += 1
                    logger.exception("[Recovery] asset enqueue failed asset_id=%s", asset_id)

            binding_rows = (
                db.query(MetaAssetBinding)
                .filter(
                    MetaAssetBinding.meta_asset_id.is_(None),
                    MetaAssetBinding.updated_at < _cutoff(),
                    or_(
                        MetaAssetBinding.status == "UPLOADING",
                        MetaAssetBinding.status == "PROCESSING",
                        MetaAssetBinding.processing_status == "UPLOADING",
                    ),
                )
                .order_by(MetaAssetBinding.updated_at.asc())
                .limit(limit)
                .all()
            )
            for binding in binding_rows:
                binding_id = binding.id
                binding.status = "PENDING"
                binding.processing_status = "PENDING"
                binding.error_code = "STALE_TASK_RECOVERED"
                binding.error_message = "检测到素材同步任务超时，已自动重新入队"
                db.commit()
                try:
                    from tasks.media_tasks import upload_asset_task

                    upload_asset_task.delay(binding_id)
                    result["bindings"] += 1
                    logger.warning("[Recovery] requeued stale binding binding_id=%s", binding_id)
                except Exception as exc:
                    db.rollback()
                    binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
                    if binding:
                        binding.status = "FAILED"
                        binding.processing_status = "FAILED"
                        binding.error_code = "TASK_ENQUEUE_FAILED"
                        binding.error_message = f"恢复素材同步任务入队失败: {exc}"[:1000]
                        db.commit()
                    result["failed"] += 1
                    logger.exception("[Recovery] binding enqueue failed binding_id=%s", binding_id)

            item_rows = (
                db.query(CampaignJobItem)
                .filter(
                    CampaignJobItem.status == JobItemStatus.RUNNING.value,
                    CampaignJobItem.updated_at < _cutoff(),
                )
                .order_by(CampaignJobItem.updated_at.asc())
                .limit(limit)
                .all()
            )
            for item in item_rows:
                job_item_id = item.id
                job = item.job
                if not job or job.status in {"SUCCESS", "FAILED", "CANCELLED"}:
                    continue
                item.status = JobItemStatus.PENDING.value
                item.error_code = "STALE_TASK_RECOVERED"
                item.error_message = "检测到投放子任务超时，已自动重新入队"
                db.commit()
                try:
                    if job.action_type == "CREATE":
                        from tasks.campaign_tasks import create_campaign_for_account

                        create_campaign_for_account.delay(job_item_id)
                    else:
                        from tasks.campaign_tasks import apply_action_for_account

                        apply_action_for_account.delay(job_item_id)
                    result["job_items"] += 1
                    logger.warning("[Recovery] requeued stale job_item job_item_id=%s", job_item_id)
                except Exception as exc:
                    db.rollback()
                    item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
                    if item:
                        item.mark_failed("TASK_ENQUEUE_FAILED", f"恢复投放子任务入队失败: {exc}")
                        db.commit()
                    result["failed"] += 1
                    logger.exception("[Recovery] job item enqueue failed job_item_id=%s", job_item_id)
        return result
    finally:
        db.close()
