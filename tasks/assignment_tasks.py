"""账户分配关系的定时维护任务。"""
from celery import shared_task
from core.database import SessionLocal
from core.tenant import for_all_tenants, bypass_tenant
from services.assignment_cleanup import release_expired_assignments


@shared_task(name="account.release_expired_assignments")
@for_all_tenants
def release_expired_assignment_task():
    db = SessionLocal()
    try:
        with bypass_tenant():
            count = release_expired_assignments(db)
        return {"status": "success", "released": count}
    finally:
        db.close()
