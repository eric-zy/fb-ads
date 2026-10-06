from datetime import date, timedelta, datetime
from typing import Optional
from celery import chain
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
from tasks.meta_sync_tasks import sync_delivery_objects_task

router = APIRouter(prefix="/api/v1/reports", tags=["报表分析"])


@router.post("/revenue-import")
def revenue_import(payload: RevenueImport, request: Request, db: Session = Depends(get_db),
                   current_user=Depends(require_permission("revenue:manage"))):
    return import_revenue(db, current_user, payload, request)

@router.post("/sync")
def sync_report_data(
    account_id: Optional[str] = Query(None),
    days: int = Query(3, ge=1, le=30),
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
    query = db.query(AdAccount).filter(AdAccount.system_status == "ACTIVE")
    if tenant_id:
        query = query.filter(AdAccount.tenant_id == tenant_id)
    if account_id:
        query = query.filter(AdAccount.id == account_id)
    accounts = query.all()
    if account_id and not accounts:
        raise HTTPException(status_code=404, detail="广告账户不存在或无权访问")
    # 报表回补必须先同步规范对象层级，再写入 Campaign/AdSet/Ad Insights。
    # 否则 Meta 已返回数据，但本地缺少父对象时，洞察会被安全地跳过。
    task_ids = []
    for account in accounts:
        account.insights_sync_status = "PENDING"
        account.insights_last_sync_error = None
        task_id = chain(
            sync_delivery_objects_task.si(account.id),
            fetch_account_insights.si(account.id, days),
        ).apply_async().id
        task_ids.append(task_id)
        # 报表同步也纳入统一任务状态接口，否则前端拿到 task_id 后无法
        # 判断链式任务是否已经真正完成，只能在提交后立即读取旧数据。
        db.add(AsyncTaskRecord(
            task_id=task_id,
            tenant_id=account.tenant_id,
            task_type="REPORT_SYNC",
            object_type="ACCOUNT_INSIGHTS",
            object_ids=[account.id],
            created_by=current_user.id,
        ))
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
    return {"status": "queued", "days": days, "account_count": len(accounts), "task_ids": task_ids}

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
    account_query = db.query(AdAccount).filter(AdAccount.system_status == "ACTIVE")
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
        # 有消耗时使用报表行的实际同步时间；无消耗时使用任务成功时间。
        # 这样不会把合法的空报表误显示成“未同步”。
        report_synced_at = item["latest_synced_at"]
        if account.insights_last_synced_at and (
            not report_synced_at or account.insights_last_synced_at > report_synced_at
        ):
            report_synced_at = account.insights_last_synced_at
        item["latest_synced_at"] = report_synced_at
        current_status = str(account.insights_sync_status or "NEVER").upper()
        if current_status == "FAILED":
            item["sync_status"] = "FAILED"
            item["sync_age_hours"] = None
        elif current_status in {"PENDING", "SYNCING"}:
            item["sync_status"] = current_status
            item["sync_age_hours"] = None
        elif report_synced_at:
            age_hours = (datetime.utcnow() - report_synced_at).total_seconds() / 3600
            item["sync_status"] = "FRESH" if age_hours <= 3 else "STALE"
            item["sync_age_hours"] = round(max(age_hours, 0), 1)
            item["latest_synced_at"] = report_synced_at.isoformat()
        else:
            item["sync_status"] = "NEVER"
            item["sync_age_hours"] = None
    for total in currency_totals.values():
        total["ctr"] = total["clicks"] / total["impressions"] * 100 if total["impressions"] else 0
        total["cpa"] = total["spend"] / total["conversions"] if total["conversions"] else 0
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
