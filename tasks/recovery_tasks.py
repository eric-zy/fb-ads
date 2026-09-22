"""恢复 Worker 重启或强制终止后遗留的国内异步任务。"""

from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import or_

from config.settings import settings
from core.database import SessionLocal
from core.enums import JobItemStatus
from core.logger import logger
from core.tenant import bypass_tenant
from models import CampaignJobItem, CreativeAsset, MetaAssetBinding, MediaUploadSession
from services.media_binding_service import queue_pending_asset_bindings
from services.storage import AliyunOSSStorage


def _cutoff() -> datetime:
    return datetime.utcnow() - timedelta(seconds=settings.ASYNC_TASK_STALE_SECONDS)


def _mark_upload_completed(db, session, asset, *, storage, result) -> bool:
    """对账一个超时上传会话；OSS 完整时补齐 complete 回调的状态变更。"""
    if not storage or not session.object_key:
        return False

    try:
        if session.upload_mode == "multipart":
            if not session.upload_id or not session.part_count:
                return False
            parts = storage.list_multipart_parts(session.object_key, session.upload_id)
            expected_parts = set(range(1, session.part_count + 1))
            actual_parts = {part["part_number"] for part in parts}
            if actual_parts != expected_parts:
                return False
            storage.complete_multipart_upload(session.object_key, session.upload_id, parts)

        head = storage.head(session.object_key)
        if session.expected_size is not None and head.size != session.expected_size:
            logger.warning(
                "[Recovery] upload size mismatch session_id=%s expected=%s actual=%s",
                session.id,
                session.expected_size,
                head.size,
            )
            return False
    except Exception as exc:
        # 未完成的 Multipart 可能只是仍在上传；不要把临时 OSS 错误当成失败。
        logger.info("[Recovery] upload not complete session_id=%s: %s", session.id, exc)
        return False

    now = datetime.utcnow()
    session.status = "COMPLETED"
    session.completed_at = now
    session.error_message = None
    if asset:
        asset.storage_status = "READY"
        asset.processing_status = "PROCESSING"
        asset.status = "PROCESSING"
        asset.error = None
    db.commit()

    # 素材解析使用租户任务，由任务自身解析 tenant_id；这里仅负责补投递。
    if asset:
        try:
            from tasks.media_tasks import process_oss_asset_task

            process_oss_asset_task.delay(asset.id)
        except Exception as exc:
            db.rollback()
            fresh_asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
            fresh_session = db.query(MediaUploadSession).filter(MediaUploadSession.id == session.id).first()
            if fresh_asset:
                fresh_asset.processing_status = "FAILED"
                fresh_asset.status = "FAILED"
                fresh_asset.error = "OSS 上传已完成，但素材处理任务投递失败，请刷新后重试"
            if fresh_session:
                fresh_session.error_message = f"素材处理任务投递失败: {exc}"[:500]
            db.commit()
            logger.exception("[Recovery] process asset enqueue failed session_id=%s", session.id)
            return False

    result["upload_sessions_recovered"] += 1
    logger.warning(
        "[Recovery] reconciled completed OSS upload session_id=%s asset_id=%s",
        session.id,
        session.asset_id,
    )
    return True


@shared_task(name="maintenance.recover_stale_domestic_work")
def recover_stale_domestic_work(limit: int = 100):
    """回收素材处理、账户素材绑定和投放子项的孤儿状态并重新入队。"""
    db = SessionLocal()
    result = {
        "assets": 0,
        "upload_sessions": 0,
        "upload_sessions_recovered": 0,
        "upload_sessions_deferred": 0,
        "upload_sessions_aborted": 0,
        "bindings": 0,
        "job_items": 0,
        "failed": 0,
    }
    try:
        # 这是系统级巡检，必须显式绕过租户过滤；重新投递的业务任务会自行解析租户。
        with bypass_tenant():
            # 先对账 OSS。浏览器可能已经把最后一个分片传完，但 complete 请求
            # 因刷新/断网没有到达 API；此时不能直接把会话判失败。
            stale_uploads = (
                db.query(MediaUploadSession)
                .filter(
                    MediaUploadSession.status == "UPLOADING",
                    MediaUploadSession.updated_at < _cutoff(),
                )
                .order_by(MediaUploadSession.updated_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
                .all()
            )
            storage = None
            try:
                storage = AliyunOSSStorage()
            except Exception as exc:
                logger.warning("[Recovery] OSS reconciliation unavailable: %s", exc)
            now = datetime.utcnow()
            for session in stale_uploads:
                asset = db.query(CreativeAsset).filter(CreativeAsset.id == session.asset_id).first()
                if session.expires_at and session.expires_at > now:
                    if _mark_upload_completed(db, session, asset, storage=storage, result=result):
                        continue
                    # 会话仍在有效期内，可能仍有分片在传；留给下一轮对账，
                    # 避免 250MB+ 视频上传超过默认巡检阈值后被误判失败。
                    result["upload_sessions_deferred"] += 1
                    continue

                # 浏览器关闭、网络中断或真正过期时，旧会话不能永久让素材库
                # 显示“处理中”。只有超过 expires_at 才标记失败。
                if storage and session.upload_mode == "multipart" and session.upload_id:
                    try:
                        storage.abort_multipart_upload(session.object_key, session.upload_id)
                        result["upload_sessions_aborted"] += 1
                        logger.info(
                            "[Recovery] aborted expired multipart session_id=%s upload_id=%s",
                            session.id,
                            session.upload_id,
                        )
                    except Exception as exc:
                        # 状态仍然要落库为 EXPIRED；OSS 侧失败会在生命周期规则中兜底清理。
                        logger.warning(
                            "[Recovery] abort expired multipart failed session_id=%s: %s",
                            session.id,
                            exc,
                        )
                session.status = "EXPIRED"
                session.error_message = "上传会话超时，已停止等待；请重新选择文件上传"
                if asset and asset.storage_status == "UPLOADING":
                    asset.storage_status = "FAILED"
                    asset.processing_status = "FAILED"
                    asset.status = "FAILED"
                    asset.error = "OSS 上传会话超时，请重新选择文件上传"
                db.commit()
                result["upload_sessions"] += 1

            asset_rows = (
                db.query(CreativeAsset)
                .filter(
                    CreativeAsset.processing_status == "PROCESSING",
                    CreativeAsset.updated_at < _cutoff(),
                    CreativeAsset.status != "ARCHIVED",
                )
                .order_by(CreativeAsset.updated_at.asc())
                .with_for_update(skip_locked=True)
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
                .with_for_update(skip_locked=True)
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
                    queued = queue_pending_asset_bindings([binding], db=db)
                    if queued:
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
                .with_for_update(skip_locked=True)
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
