"""Custom Audience 元数据异步同步任务。"""

from datetime import datetime
from typing import Dict

from celery import shared_task

from core.database import SessionLocal
from core.logger import logger
from core.tenant import resolve_tenant_of, tenant_task
from models import AdAccount, AsyncTaskRecord
from services.meta_audience_service import MetaAudienceSyncService


@shared_task(bind=True, name="meta.sync_custom_audiences", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, account_pk: resolve_tenant_of(AdAccount, account_pk))
def sync_custom_audiences_task(self, account_pk: str) -> Dict:
    """后台同步单个广告账户的 Custom Audience 元数据。"""
    db = SessionLocal()
    task_id = str(self.request.id or "")
    try:
        record = db.query(AsyncTaskRecord).filter(AsyncTaskRecord.task_id == task_id).first()
        if record:
            record.status = "STARTED"
            db.commit()
        result = MetaAudienceSyncService(db).sync_account(account_pk)
        if record:
            record.status = "SUCCESS"
            record.result_summary = {"status": "SUCCESS", "count": result.get("count", 0)}
            record.finished_at = datetime.utcnow()
            db.commit()
        logger.info(
            "[meta_audiences] sync success account_pk=%s account_id=%s count=%s",
            account_pk,
            result.get("account_id"),
            result.get("count", 0),
        )
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("[meta_audiences] sync failed account_pk=%s error=%s", account_pk, exc)
        try:
            record = db.query(AsyncTaskRecord).filter(AsyncTaskRecord.task_id == task_id).first()
            if record:
                record.status = "RETRY"
                record.result_summary = {"status": "RETRY", "error": str(exc)}
                db.commit()
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            record = db.query(AsyncTaskRecord).filter(AsyncTaskRecord.task_id == task_id).first()
            if record:
                record.status = "FAILURE"
                record.result_summary = {"status": "FAILED", "error": str(exc)}
                record.finished_at = datetime.utcnow()
                db.commit()
            return {
                "status": "FAILED",
                "account_pk": account_pk,
                "error": str(exc),
            }
    finally:
        db.close()
