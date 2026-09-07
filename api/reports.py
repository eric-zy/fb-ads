from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from core.auth import get_current_active_user
from core.database import get_db
from core.money import to_major
from models import AccountInsight, CampaignInsight, AdSetInsight, AdInsight

router = APIRouter(prefix="/api/v1/reports", tags=["报表分析"])

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
    series = [{"date": str(row.date), "spend": to_major(row.spend or 0), "revenue": to_major(row.revenue) if row.revenue is not None else None, "profit": to_major(row.profit) if row.profit is not None else None, "roi": row.roi, "impressions": row.impressions or 0, "clicks": row.clicks or 0, "conversions": row.conversions or 0, "ctr": row.ctr or 0, "cpc": row.cpc or 0, "cpm": row.cpm or 0, "roas": getattr(row, "roas", 0) or 0} for row in rows]
    return {"dimension": dimension, "entity_id": entity_id, "days": days, "total": {"spend": sum(item["spend"] for item in series), "revenue": sum(item["revenue"] or 0 for item in series), "profit": sum(item["profit"] or 0 for item in series), "impressions": sum(item["impressions"] for item in series), "clicks": sum(item["clicks"] for item in series), "conversions": sum(item["conversions"] for item in series)}, "series": series}
