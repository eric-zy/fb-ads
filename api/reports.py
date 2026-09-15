from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from core.auth import get_current_active_user
from core.database import get_db
from core.money import to_major
from models import AccountInsight, CampaignInsight, AdSetInsight, AdInsight, Campaign, AdGroup, Ad, AdAccount

router = APIRouter(prefix="/api/v1/reports", tags=["报表分析"])

@router.get("/breakdown")
def report_breakdown(
    dimension: str = Query("account"),
    days: int = Query(30, ge=1, le=90),
    parent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """返回指定层级的汇总行，供前端逐级钻取使用。"""
    models = {"account": (AccountInsight, "ad_account_id"), "campaign": (CampaignInsight, "campaign_id"), "adset": (AdSetInsight, "ad_group_id"), "ad": (AdInsight, "ad_id")}
    if dimension not in models:
        raise HTTPException(status_code=400, detail="不支持的报表维度")
    model, key_name = models[dimension]
    names = {}
    if dimension == "account":
        names = {x.id: (x.account_name or x.account_id) for x in db.query(AdAccount).all()}
    elif dimension == "campaign":
        names = {x.id: x.name for x in db.query(Campaign).all()}
    elif dimension == "adset":
        names = {x.id: x.name for x in db.query(AdGroup).all()}
    else:
        names = {x.id: x.name for x in db.query(Ad).all()}
    query = db.query(model).filter(model.date >= date.today() - timedelta(days=days))
    if parent_id and dimension != "account":
        if dimension == "campaign":
            ids = [x.id for x in db.query(Campaign).filter(Campaign.ad_account_id == parent_id).all()]
        elif dimension == "adset":
            ids = [x.id for x in db.query(AdGroup).filter(AdGroup.campaign_id == parent_id).all()]
        else:
            ids = [x.id for x in db.query(Ad).filter(Ad.ad_group_id == parent_id).all()]
        query = query.filter(getattr(model, key_name).in_(ids or ["__none__"]))
    elif parent_id and dimension == "account":
        query = query.filter(model.ad_account_id == parent_id)
    rows = query.all()
    grouped = {}
    for row in rows:
        key = getattr(row, key_name)
        item = grouped.setdefault(key, {"entity_id": key, "entity_name": names.get(key, key), "spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "conversion_value": 0})
        item["spend"] += to_major(row.spend or 0)
        item["impressions"] += row.impressions or 0
        item["clicks"] += row.clicks or 0
        item["conversions"] += row.conversions or 0
        item["conversion_value"] += to_major(getattr(row, "conversion_value", 0) or 0)
    for item in grouped.values():
        item["ctr"] = item["clicks"] / item["impressions"] * 100 if item["impressions"] else 0
        item["conversion_rate"] = item["conversions"] / item["clicks"] * 100 if item["clicks"] else 0
        item["cpa"] = item["spend"] / item["conversions"] if item["conversions"] else 0
        item["roas"] = item["conversion_value"] / item["spend"] if item["spend"] else 0
    return {"dimension": dimension, "days": days, "parent_id": parent_id, "items": sorted(grouped.values(), key=lambda item: item["spend"], reverse=True)}

@router.get("/trend")
def report_trend(
    dimension: str = Query("account"),
    entity_id: Optional[str] = None,
    days: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    models = {"account": (AccountInsight, "ad_account_id"), "campaign": (CampaignInsight, "campaign_id"), "adset": (AdSetInsight, "ad_group_id"), "ad": (AdInsight, "ad_id")}
    if dimension not in models:
        raise HTTPException(status_code=400, detail="不支持的报表维度")
    model, entity_column = models[dimension]
    query = db.query(model).filter(model.date >= date.today() - timedelta(days=days))
    if entity_id:
        query = query.filter(getattr(model, entity_column) == entity_id)
    rows = query.order_by(model.date.asc()).all()
    series = [{"date": str(row.date), "spend": to_major(row.spend or 0), "revenue": to_major(row.revenue) if row.revenue is not None else None, "profit": to_major(row.profit) if row.profit is not None else None, "conversion_value": to_major(row.conversion_value) if getattr(row, "conversion_value", None) is not None else 0, "roi": row.roi, "impressions": row.impressions or 0, "clicks": row.clicks or 0, "conversions": row.conversions or 0, "ctr": (row.ctr or 0) * 100, "cpc": row.cpc or 0, "cpm": row.cpm or 0, "roas": getattr(row, "roas", 0) or 0} for row in rows]
    for item, row in zip(series, rows):
        item["link_clicks"] = getattr(row, "link_clicks", 0) or 0
        item["landing_page_views"] = getattr(row, "landing_page_views", 0) or 0
        item["leads"] = getattr(row, "leads", 0) or 0
        item["purchases"] = getattr(row, "purchases", 0) or 0
        item["conversion_rate"] = (item["conversions"] / item["clicks"] * 100) if item["clicks"] else 0
        item["cpa"] = item["spend"] / item["conversions"] if item["conversions"] else 0
        item["roas"] = item["conversion_value"] / item["spend"] if item["spend"] else 0
    total_clicks = sum(item["clicks"] for item in series)
    total_conversions = sum(item["conversions"] for item in series)
    total_spend = sum(item["spend"] for item in series)
    total = {"spend": total_spend, "revenue": sum(item["revenue"] or 0 for item in series), "profit": sum(item["profit"] or 0 for item in series), "conversion_value": sum(item["conversion_value"] for item in series), "impressions": sum(item["impressions"] for item in series), "clicks": total_clicks, "conversions": total_conversions, "conversion_rate": (total_conversions / total_clicks * 100) if total_clicks else 0, "roas": (sum(item["conversion_value"] for item in series) / total_spend) if total_spend else 0}
    synced = [row.synced_at for row in rows if getattr(row, "synced_at", None)]
    return {"dimension": dimension, "entity_id": entity_id, "days": days, "total": total, "series": series, "data_quality": {"row_count": len(rows), "latest_synced_at": max(synced).isoformat() if synced else None, "has_data": bool(rows)}}
