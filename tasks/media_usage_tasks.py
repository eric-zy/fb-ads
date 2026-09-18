"""素材使用统计的可重算汇总任务。"""
from datetime import date, datetime, timedelta
import uuid

from celery import shared_task
from sqlalchemy import case, func

from core.database import SessionLocal
from core.tenant import for_all_tenants
from models import CreativeAssetUsageAccountDailyStat, CreativeAssetUsageDailyStat, CreativeAssetUsageEvent


@shared_task(name="media.rebuild_usage_daily_stats")
@for_all_tenants
def rebuild_usage_daily_stats(days: int = 3) -> dict:
    """重算最近 N 天的素材使用汇总，事件表仍是唯一事实来源。"""
    days = max(int(days or 3), 1)
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days - 1)
    db = SessionLocal()
    try:
        db.query(CreativeAssetUsageDailyStat).filter(
            CreativeAssetUsageDailyStat.stat_date >= start_date,
            CreativeAssetUsageDailyStat.stat_date <= end_date,
        ).delete(synchronize_session=False)
        db.query(CreativeAssetUsageAccountDailyStat).filter(
            CreativeAssetUsageAccountDailyStat.stat_date >= start_date,
            CreativeAssetUsageAccountDailyStat.stat_date <= end_date,
        ).delete(synchronize_session=False)

        day_expression = func.date(CreativeAssetUsageEvent.occurred_at)
        rows = db.query(
            CreativeAssetUsageEvent.tenant_id,
            CreativeAssetUsageEvent.asset_id,
            day_expression,
            func.count(CreativeAssetUsageEvent.id),
            func.sum(case((CreativeAssetUsageEvent.status == "SUCCESS", 1), else_=0)),
            func.sum(case((CreativeAssetUsageEvent.status == "FAILED", 1), else_=0)),
            func.max(CreativeAssetUsageEvent.occurred_at),
        ).filter(
            CreativeAssetUsageEvent.occurred_at >= datetime.combine(start_date, datetime.min.time()),
            CreativeAssetUsageEvent.occurred_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
        ).group_by(
            CreativeAssetUsageEvent.tenant_id,
            CreativeAssetUsageEvent.asset_id,
            day_expression,
        ).all()

        for tenant_id, asset_id, stat_date, total, success, failed, last_used_at in rows:
            if isinstance(stat_date, datetime):
                stat_date = stat_date.date()
            elif isinstance(stat_date, str):
                stat_date = date.fromisoformat(stat_date)
            db.add(CreativeAssetUsageDailyStat(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                asset_id=asset_id,
                stat_date=stat_date,
                usage_count=int(total or 0),
                successful_usage_count=int(success or 0),
                failed_usage_count=int(failed or 0),
                last_used_at=last_used_at,
            ))
        account_rows = db.query(
            CreativeAssetUsageEvent.tenant_id,
            CreativeAssetUsageEvent.asset_id,
            CreativeAssetUsageEvent.ad_account_id,
            day_expression,
            func.count(CreativeAssetUsageEvent.id),
            func.sum(case((CreativeAssetUsageEvent.status == "SUCCESS", 1), else_=0)),
            func.sum(case((CreativeAssetUsageEvent.status == "FAILED", 1), else_=0)),
            func.max(CreativeAssetUsageEvent.occurred_at),
        ).filter(
            CreativeAssetUsageEvent.occurred_at >= datetime.combine(start_date, datetime.min.time()),
            CreativeAssetUsageEvent.occurred_at < datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
        ).group_by(
            CreativeAssetUsageEvent.tenant_id,
            CreativeAssetUsageEvent.asset_id,
            CreativeAssetUsageEvent.ad_account_id,
            day_expression,
        ).all()
        for tenant_id, asset_id, ad_account_id, stat_date, total, success, failed, last_used_at in account_rows:
            if isinstance(stat_date, datetime):
                stat_date = stat_date.date()
            elif isinstance(stat_date, str):
                stat_date = date.fromisoformat(stat_date)
            db.add(CreativeAssetUsageAccountDailyStat(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                asset_id=asset_id,
                ad_account_id=ad_account_id,
                stat_date=stat_date,
                usage_count=int(total or 0),
                successful_usage_count=int(success or 0),
                failed_usage_count=int(failed or 0),
                last_used_at=last_used_at,
            ))
        db.commit()
        return {"status": "success", "days": days, "rows": len(rows), "account_rows": len(account_rows)}
    finally:
        db.close()
