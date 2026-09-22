"""按当前用户可见范围汇总工作台数据。

工作台只负责读取已经落库的报表、投放对象、任务和告警，不在页面请求期间
同步 Meta。所有查询都先经过租户和广告账户范围过滤，前端传入的 account_id
只能缩小当前用户的可见范围，不能扩大权限。
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from core.money import to_major
from core.tenant import effective_tenant_id
from models import (
    AccountInsight,
    AdAccount,
    CampaignInstance,
    CampaignJob,
    CampaignJobItem,
    SyncAlert,
)
from services.account_access import accessible_account_ids


router = APIRouter(prefix="/api/v1/workbench", tags=["工作台"])

_ACTIVE_JOB_STATUSES = {"PENDING", "VALIDATING", "QUEUED", "RUNNING"}
_FAILED_JOB_STATUSES = {"FAILED", "PARTIAL_SUCCESS"}


def _derived_metrics(values: dict) -> dict:
    """按同一统计粒度计算比率，分母不存在时返回 None 而不是伪造 0。"""
    spend = float(values.get("spend") or 0)
    impressions = int(values.get("impressions") or 0)
    clicks = int(values.get("clicks") or 0)
    conversions = int(values.get("conversions") or 0)
    conversion_value = float(values.get("conversion_value") or 0)
    return {
        "ctr": round(clicks / impressions * 100, 4) if impressions else None,
        "conversion_rate": round(conversions / clicks * 100, 4) if clicks else None,
        "cpc": round(spend / clicks, 4) if clicks else None,
        "cpm": round(spend / impressions * 1000, 4) if impressions else None,
        "cpa": round(spend / conversions, 4) if conversions else None,
        "roas": round(conversion_value / spend, 4) if spend else None,
    }


def _scope(query, model, user, tenant_id: Optional[str]):
    """显式加租户范围；平台管理员无租户上下文时才允许平台范围查询。"""
    if tenant_id:
        return query.filter(model.tenant_id == tenant_id)
    if getattr(user, "is_platform_admin", lambda: False)():
        return query
    raise HTTPException(status_code=403, detail="当前账号未绑定租户")


def _freshness(timestamp: Optional[datetime]) -> dict:
    if not timestamp:
        return {"status": "NEVER", "latest_synced_at": None, "age_hours": None}
    age_hours = max((datetime.utcnow() - timestamp).total_seconds() / 3600, 0)
    return {
        "status": "FRESH" if age_hours <= 3 else "STALE",
        "latest_synced_at": timestamp.isoformat(),
        "age_hours": round(age_hours, 1),
    }


def _accounts_in_scope(db: Session, current_user, tenant_id: Optional[str], account_id: Optional[str] = None):
    """返回当前用户可见的账户；account_id 只能进一步缩小范围。"""
    visible_ids = accessible_account_ids(db, current_user)
    account_query = _scope(db.query(AdAccount), AdAccount, current_user, tenant_id)
    if visible_ids is not None:
        account_query = account_query.filter(AdAccount.id.in_(visible_ids or {"__no_accounts__"}))
    if account_id:
        if visible_ids is not None and account_id not in visible_ids:
            raise HTTPException(status_code=404, detail="广告账户不存在或无权访问")
        account_query = account_query.filter(AdAccount.id == account_id)
    accounts = account_query.order_by(AdAccount.account_name.asc(), AdAccount.id.asc()).all()
    if account_id and not accounts:
        raise HTTPException(status_code=404, detail="广告账户不存在或无权访问")
    return accounts


@router.get("/summary")
def workbench_summary(
    account_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """返回工作台首页所需的单次聚合结果，并严格限制到当前用户可见账户。"""
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=6))
    if start > end:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="工作台时间范围不能超过 90 天")

    tenant_id = effective_tenant_id(current_user)
    accounts = _accounts_in_scope(db, current_user, tenant_id, account_id)

    account_ids = [account.id for account in accounts]
    account_map = {account.id: account for account in accounts}
    empty_ids = ["__no_visible_accounts__"]

    # Insights：按日期和币种汇总，避免跨币种直接相加。
    insight_query = db.query(
        AccountInsight.date.label("insight_date"),
        AccountInsight.ad_account_id.label("account_id"),
        func.coalesce(func.sum(AccountInsight.spend), 0).label("spend"),
        func.coalesce(func.sum(AccountInsight.impressions), 0).label("impressions"),
        func.coalesce(func.sum(AccountInsight.clicks), 0).label("clicks"),
        func.coalesce(func.sum(AccountInsight.conversions), 0).label("conversions"),
        func.coalesce(func.sum(AccountInsight.conversion_value), 0).label("conversion_value"),
        func.max(AccountInsight.synced_at).label("latest_synced_at"),
    ).filter(
        AccountInsight.date >= start,
        AccountInsight.date <= end,
        AccountInsight.ad_account_id.in_(account_ids or empty_ids),
    )
    if tenant_id:
        insight_query = insight_query.filter(AccountInsight.tenant_id == tenant_id)
    insight_rows = insight_query.group_by(AccountInsight.date, AccountInsight.ad_account_id).all()

    totals = defaultdict(lambda: {
        "spend": 0.0,
        "impressions": 0,
        "clicks": 0,
        "conversions": 0,
        "conversion_value": 0.0,
    })
    trend = defaultdict(lambda: defaultdict(float))
    latest_synced_at = None
    total_impressions = total_clicks = 0
    account_latest_synced_at = {account.id: account.last_synced_at for account in accounts}

    for row in insight_rows:
        account = account_map.get(row.account_id)
        if not account:
            continue
        currency = (account.currency or "USD").upper()
        spend = to_major(row.spend or 0, currency)
        conversion_value = to_major(row.conversion_value or 0, currency)
        total = totals[currency]
        total["spend"] += spend
        total["impressions"] += int(row.impressions or 0)
        total["clicks"] += int(row.clicks or 0)
        total["conversions"] += int(row.conversions or 0)
        total["conversion_value"] += conversion_value
        trend[(row.insight_date.isoformat(), currency)]["spend"] += spend
        trend[(row.insight_date.isoformat(), currency)]["impressions"] += int(row.impressions or 0)
        trend[(row.insight_date.isoformat(), currency)]["clicks"] += int(row.clicks or 0)
        trend[(row.insight_date.isoformat(), currency)]["conversions"] += int(row.conversions or 0)
        trend[(row.insight_date.isoformat(), currency)]["conversion_value"] += conversion_value
        total_impressions += int(row.impressions or 0)
        total_clicks += int(row.clicks or 0)
        if row.latest_synced_at and (not latest_synced_at or row.latest_synced_at > latest_synced_at):
            latest_synced_at = row.latest_synced_at
        if row.latest_synced_at and (
            not account_latest_synced_at.get(row.account_id)
            or row.latest_synced_at > account_latest_synced_at[row.account_id]
        ):
            account_latest_synced_at[row.account_id] = row.latest_synced_at

    if not latest_synced_at:
        account_sync_times = [row.last_synced_at for row in accounts if row.last_synced_at]
        latest_synced_at = max(account_sync_times) if account_sync_times else None

    currency_totals = []
    for currency, total in sorted(totals.items()):
        spend = total["spend"]
        conversions = total["conversions"]
        currency_totals.append({
            "currency": currency,
            "spend": round(spend, 2),
            "impressions": total["impressions"],
            "clicks": total["clicks"],
            "conversions": conversions,
            "conversion_value": round(total["conversion_value"], 2),
            **_derived_metrics(total),
        })

    trend_rows = []
    for (trend_date, currency), values in sorted(trend.items()):
        trend_rows.append({
            "date": trend_date,
            "currency": currency,
            "spend": round(values["spend"], 2),
            "impressions": values["impressions"],
            "clicks": values["clicks"],
            "conversions": values["conversions"],
            "conversion_value": round(values["conversion_value"], 2),
            **_derived_metrics(values),
        })

    # 投放对象健康度。
    campaign_query = _scope(db.query(CampaignInstance), CampaignInstance, current_user, tenant_id)
    campaign_query = campaign_query.filter(CampaignInstance.ad_account_id.in_(account_ids or empty_ids))
    campaign_status_rows = campaign_query.with_entities(
        CampaignInstance.status, func.count(CampaignInstance.id)
    ).group_by(CampaignInstance.status).all()
    campaign_status = {str(status): int(count) for status, count in campaign_status_rows}
    drift_count = campaign_query.filter(
        CampaignInstance.desired_status.isnot(None),
        CampaignInstance.meta_status.isnot(None),
        CampaignInstance.desired_status != CampaignInstance.meta_status,
    ).count()

    # Job Center：只统计有当前用户可见账户子项的任务，防止通过数量侧信道泄漏其他账户。
    # 不要对包含 JSON 字段（CampaignJob.params）的实体查询直接调用 DISTINCT。
    # PostgreSQL 的 json 类型没有等值操作符，会导致工作台接口 500；先取
    # 可见 job_id，再按主键过滤任务实体，同时保持租户和账户范围隔离。
    visible_job_ids = db.query(CampaignJobItem.job_id).filter(
        CampaignJobItem.ad_account_id.in_(account_ids or empty_ids),
    )
    if tenant_id:
        visible_job_ids = visible_job_ids.filter(CampaignJobItem.tenant_id == tenant_id)
    job_query = _scope(db.query(CampaignJob), CampaignJob, current_user, tenant_id)
    job_query = job_query.filter(CampaignJob.id.in_(visible_job_ids))
    job_status_rows = job_query.with_entities(
        CampaignJob.status, func.count(CampaignJob.id)
    ).group_by(CampaignJob.status).all()
    job_status = {str(status): int(count) for status, count in job_status_rows}

    recent_jobs = job_query.order_by(CampaignJob.created_at.desc()).limit(8).all()
    recent_job_ids = [job.id for job in recent_jobs]
    recent_items = db.query(CampaignJobItem).filter(
        CampaignJobItem.job_id.in_(recent_job_ids or ["__no_jobs__"]),
        CampaignJobItem.ad_account_id.in_(account_ids or empty_ids),
    )
    if tenant_id:
        recent_items = recent_items.filter(CampaignJobItem.tenant_id == tenant_id)
    items_by_job = defaultdict(list)
    for item in recent_items.all():
        items_by_job[item.job_id].append(item)

    recent_tasks = []
    for job in recent_jobs:
        items = items_by_job[job.id]
        if not items:
            continue
        recent_tasks.append({
            "id": job.id,
            "action_type": job.action_type,
            "status": job.status,
            "total_accounts": len(items),
            "success_count": sum(item.status in ("SUCCESS", "SKIPPED") for item in items),
            "failed_count": sum(item.status == "FAILED" for item in items),
            "created_by": job.created_by,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        })

    alert_query = _scope(db.query(SyncAlert), SyncAlert, current_user, tenant_id).filter(
        SyncAlert.is_resolved.is_(False),
        SyncAlert.ad_account_id.in_(account_ids or empty_ids),
    )
    open_alert_count = alert_query.count()
    alerts = [row.to_dict() for row in alert_query.order_by(SyncAlert.created_at.desc()).limit(8).all()]

    account_freshness = {
        account.id: _freshness(account_latest_synced_at.get(account.id))
        for account in accounts
    }
    never_synced_count = sum(item["status"] == "NEVER" for item in account_freshness.values())
    stale_count = sum(item["status"] == "STALE" for item in account_freshness.values())
    if not accounts or never_synced_count == len(accounts):
        freshness_status = "NEVER"
    elif stale_count or never_synced_count:
        freshness_status = "STALE"
    else:
        freshness_status = "FRESH"
    freshness = {
        **_freshness(latest_synced_at),
        "status": freshness_status,
        "account_count": len(accounts),
        "stale_account_count": stale_count,
        "never_synced_account_count": never_synced_count,
    }

    visible_accounts = [
        {
            "id": account.id,
            "name": account.account_name or account.account_id,
            "currency": (account.currency or "USD").upper(),
            "system_status": account.system_status,
            "freshness": account_freshness[account.id],
        }
        for account in accounts
    ]
    return {
        "scope": {
            "tenant_id": tenant_id,
            "role": current_user.role,
            "selected_account_id": account_id,
            "account_count": len(accounts),
            "accounts": visible_accounts,
        },
        "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "freshness": freshness,
        "kpis": {
            "active_campaigns": campaign_status.get("ACTIVE", 0),
            "total_campaigns": sum(count for status, count in campaign_status.items() if status != "DELETED"),
            "average_ctr": round(total_clicks / total_impressions * 100, 4) if total_impressions else 0,
            "pending_jobs": sum(job_status.get(status, 0) for status in _ACTIVE_JOB_STATUSES),
            "failed_jobs": sum(job_status.get(status, 0) for status in _FAILED_JOB_STATUSES),
            "open_alerts": open_alert_count,
            "status_drift": drift_count,
            "highest_risk_score": round(max((float(account.risk_score or 0) for account in accounts), default=0), 4),
        },
        "delivery_health": {
            "status_counts": campaign_status,
            "status_drift": drift_count,
        },
        "job_status": job_status,
        "currency_totals": currency_totals,
        "trend": trend_rows,
        "recent_tasks": recent_tasks,
        "alerts": alerts,
    }


@router.get("/notifications")
def workbench_notifications(
    account_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """返回顶部通知徽标所需的轻量统计，避免重复加载完整告警和任务列表。"""
    tenant_id = effective_tenant_id(current_user)
    accounts = _accounts_in_scope(db, current_user, tenant_id, account_id)
    account_ids = [account.id for account in accounts]
    empty_ids = ["__no_visible_accounts__"]

    alert_query = _scope(db.query(SyncAlert), SyncAlert, current_user, tenant_id).filter(
        SyncAlert.is_resolved.is_(False),
        SyncAlert.ad_account_id.in_(account_ids or empty_ids),
    )
    visible_job_ids = db.query(CampaignJobItem.job_id).filter(
        CampaignJobItem.ad_account_id.in_(account_ids or empty_ids),
    )
    if tenant_id:
        visible_job_ids = visible_job_ids.filter(CampaignJobItem.tenant_id == tenant_id)
    job_query = _scope(db.query(CampaignJob), CampaignJob, current_user, tenant_id).filter(
        CampaignJob.id.in_(visible_job_ids),
        CampaignJob.status.in_(_FAILED_JOB_STATUSES),
    )
    alert_count = alert_query.count()
    failed_job_count = job_query.with_entities(func.count(CampaignJob.id)).scalar() or 0
    return {
        "alerts": alert_count,
        "failed_jobs": int(failed_job_count),
        "total": alert_count + int(failed_job_count),
    }
