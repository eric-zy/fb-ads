from datetime import date, timedelta, datetime
from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from core.auth import get_current_active_user, require_admin, require_permission
from services.revenue import RevenueImport, import_revenue
from core.audit import record_audit
from core.tenant import effective_tenant_id
from core.database import get_db
from core.money import to_major
from models import AccountInsight, CampaignInsight, AdSetInsight, AdInsight, Campaign, AdGroup, Ad, AdAccount, AsyncTaskRecord
from services.account_access import accessible_account_ids
from tasks.celery_tasks import fetch_account_insights
from services.report_quality import report_quality

router = APIRouter(prefix="/api/v1/reports", tags=["报表分析"])


@router.post("/revenue-import")
def revenue_import(payload: RevenueImport, request: Request, db: Session = Depends(get_db),
                   current_user=Depends(require_permission("revenue:manage"))):
    return import_revenue(db, current_user, payload, request)

@router.post("/sync")
def sync_report_data(
    account_id: Optional[str] = Query(None),
    days: int = Query(3, ge=1, le=90),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员手动回补账户 Insights；只允许操作当前租户账户。"""
    tenant_id = effective_tenant_id(current_user)
    # 平台管理员未切换租户时不得触发跨租户全量写入；如确需处理，
    # 必须显式指定一个本地广告账户，任务随后按该账户租户执行。
    if not tenant_id and not account_id:
        raise HTTPException(
            status_code=400,
            detail="请先切换到目标租户，或显式指定 account_id",
        )
    if bool(start_date) != bool(end_date):
        raise HTTPException(400, "start_date 和 end_date 必须同时提供")
    if start_date and (start_date > end_date or (end_date - start_date).days >= 90):
        raise HTTPException(400, "同步窗口必须为 1 至 90 天")
    query = db.query(AdAccount).filter(AdAccount.system_status.in_(["ACTIVE", "DISABLED"]))
    if tenant_id:
        query = query.filter(AdAccount.tenant_id == tenant_id)
    if account_id:
        query = query.filter(AdAccount.id == account_id)
    accounts = query.all()
    if account_id and not accounts:
        raise HTTPException(status_code=404, detail="广告账户不存在或无权访问")
    task_ids = []
    for account in accounts:
        task_id = uuid.uuid4().hex
        task_ids.append(task_id)
        account.insights_sync_status = "PENDING"
        account.insights_last_sync_error = None
        db.add(AsyncTaskRecord(task_id=task_id, tenant_id=account.tenant_id,
                               task_type="REPORT_SYNC", object_type="ACCOUNT_INSIGHTS",
                               object_ids=[account.id], created_by=current_user.id))
    # Persist ownership before dispatch; a fast worker can now find its record.
    db.commit()
    failures = []
    for account, task_id in zip(accounts, task_ids):
        try:
            fetch_account_insights.apply_async(args=[account.id, days],
                kwargs={"start_date": str(start_date) if start_date else None,
                        "end_date": str(end_date) if end_date else None}, task_id=task_id)
        except Exception as exc:
            account.insights_sync_status = "FAILED"
            account.insights_last_sync_error = f"报表任务入队失败：{exc}"[:2000]
            record = db.query(AsyncTaskRecord).filter_by(task_id=task_id).one()
            record.status = "FAILED"
            record.result_summary = {"status": "failed", "error": account.insights_last_sync_error}
            record.finished_at = datetime.utcnow()
            failures.append(task_id)
    db.commit()
    record_audit(
        db,
        action="SYNC_REPORT_DATA",
        resource_type="ad_account",
        resource_id=account_id or "batch",
        user_id=current_user.id,
        request_data={"account_id": account_id, "days": days, "account_count": len(accounts)},
        response_data={"status": "QUEUED", "task_ids": task_ids},
    )
    return {"status": "partial_failure" if failures else "queued", "days": days, "account_count": len(accounts), "task_ids": task_ids, "failed_task_ids": failures}

@router.get("/account-overview")
def account_overview(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """按广告账户汇总消耗，并返回同步新鲜度。"""
    end = end_date or date.today()
    # 回补任务默认同步最近 3 天；总览也必须使用同一窗口，否则当天尚无
    # 消耗时页面会把已同步的前几天数据误显示为全 0。
    start = start_date or (end - timedelta(days=2))
    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    tenant_id = effective_tenant_id(current_user)
    account_query = db.query(AdAccount).filter(AdAccount.system_status.in_(["ACTIVE", "DISABLED"]))
    if tenant_id:
        account_query = account_query.filter(AdAccount.tenant_id == tenant_id)
    if not current_user.is_admin():
        visible_ids = accessible_account_ids(db, current_user)
        account_query = account_query.filter(AdAccount.id.in_(visible_ids or {"__no_accounts__"}))
    accounts = account_query.all()
    account_map = {account.id: account for account in accounts}
    q = db.query(AccountInsight).filter(
        AccountInsight.date >= start, AccountInsight.date <= end,
        AccountInsight.ad_account_id.in_(list(account_map) or ["__none__"]),
    )
    grouped = {
        account.id: {
            "account_id": account.id, "meta_account_id": account.account_id,
            "account_name": account.account_name or account.account_id,
            "currency": account.currency or "USD", "system_status": account.system_status,
            "spend": 0, "impressions": 0, "clicks": 0, "conversions": 0,
            "conversion_value": 0,
            "latest_synced_at": None,
            "sync_status": account.insights_sync_status or "NEVER",
            "sync_error": account.insights_last_sync_error,
        } for account in accounts
    }
    for row in q.all():
        account = account_map[row.ad_account_id]
        item = grouped[row.ad_account_id]
        item["spend"] += to_major(row.spend or 0, account.currency)
        item["impressions"] += row.impressions or 0
        item["clicks"] += row.clicks or 0
        item["conversions"] += row.conversions or 0
        item["conversion_value"] += to_major(row.conversion_value or 0, account.currency)
        if row.synced_at and (not item["latest_synced_at"] or row.synced_at > item["latest_synced_at"]):
            item["latest_synced_at"] = row.synced_at
    items = list(grouped.values())
    currency_totals = {}
    for item in items:
        item["ctr"] = item["clicks"] / item["impressions"] * 100 if item["impressions"] else 0
        item["cpa"] = item["spend"] / item["conversions"] if item["conversions"] else 0
        item["roas"] = item["conversion_value"] / item["spend"] if item["spend"] else 0
        currency = item["currency"]
        total = currency_totals.setdefault(currency, {"currency": currency, "spend": 0, "impressions": 0, "clicks": 0, "conversions": 0})
        total["spend"] += item["spend"]
        total["impressions"] += item["impressions"]
        total["clicks"] += item["clicks"]
        total["conversions"] += item["conversions"]
        account = account_map[item["account_id"]]
        quality = report_quality(db, account, start, end)
        item["sync_status"] = quality["status"]
        item["latest_synced_at"] = quality["latest_synced_at"]
        item["sync_age_hours"] = quality["age_hours"]
        item["data_quality"] = quality

    return {
        "start_date": str(start), "end_date": str(end),
        "items": sorted(items, key=lambda x: x["spend"], reverse=True),
        "currency_totals": sorted(currency_totals.values(), key=lambda x: x["spend"], reverse=True),
        "currency_note": "不同币种未进行汇率换算，currency_totals 分组展示",
    }

@router.get("/breakdown")
def report_breakdown(
    dimension: str = Query("account"),
    days: int = Query(30, ge=1, le=90),
    parent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    from services.reporting import breakdown
    return breakdown(db, current_user, dimension, days, parent_id)


@router.get("/trend")
def report_trend(
    dimension: str = Query("account"),
    entity_id: Optional[str] = None,
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    from services.reporting import trend
    return trend(db, current_user, dimension, days, entity_id)
