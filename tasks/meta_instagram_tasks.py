from datetime import datetime

from celery import shared_task

from core.database import SessionLocal
from core.tenant import resolve_tenant_of, tenant_task
from models import AdAccount, AsyncTaskRecord
from services.meta_instagram_service import MetaInstagramSyncService


@shared_task(bind=True, name="meta.sync_instagram", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, account_pk: resolve_tenant_of(AdAccount, account_pk))
def sync_instagram_task(self, account_pk: str):
    db = SessionLocal()
    try:
        record = db.query(AsyncTaskRecord).filter(AsyncTaskRecord.task_id == str(self.request.id)).first()
        if record:
            record.status = "STARTED"
            db.commit()
        try:
            result = MetaInstagramSyncService(db).sync_account(account_pk)
        except Exception as exc:
            db.rollback()
            if self.request.retries < self.max_retries:
                if record:
                    record.status = "RETRY"
                    db.commit()
                raise self.retry(exc=exc)
            result = {"status": "FAILED", "error": "Instagram 身份同步失败，请检查授权及 Connector 状态"}
        if record:
            record.status = "FAILURE" if result["status"] == "FAILED" else "SUCCESS"
            record.result_summary = result
            record.finished_at = datetime.utcnow()
            db.commit()
        return result
    finally:
        db.close()
