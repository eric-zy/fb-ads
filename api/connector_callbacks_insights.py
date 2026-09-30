from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from config.settings import settings
from services.request_signer import verify_request
from models import AccountInsight, AdAccount, MetaAccount
from models.connector_insights import ConnectorInsightsSnapshot
from core.database import get_db
from core.logger import logger
from core.money import to_minor, to_major
from core.tenant import bypass_tenant, tenant_scope
from services.ads_manager import AdsManager
from sqlalchemy.orm import Session
from datetime import datetime, date
import hashlib
import uuid

router = APIRouter(prefix="/api/v1/internal/fb-connector", tags=["FB Connector 报表回调"])

class InsightsCallback(BaseModel):
    event: str = "insights.completed"
    request_id: str
    credential_id: str
    account_id: str
    days: int = Field(..., ge=1, le=90)
    items: list[dict] = Field(default_factory=list)


def _account_ref(value: str) -> str:
    value = str(value or "").strip()
    return value if value.startswith("act_") else f"act_{value}"


def _upsert_account_insights(db: Session, account: AdAccount, items: list[dict]) -> int:
    """将 Connector 账户级结果写入 SaaS canonical account_insights。"""
    count = 0
    for row in items:
        raw_date = row.get("date_start") or row.get("date_stop")
        try:
            insight_date = date.fromisoformat(str(raw_date)[:10])
        except (TypeError, ValueError):
            continue

        metrics = AdsManager._parse_action_metrics(
            row.get("actions"), row.get("action_values")
        )
        spend = to_minor(float(row.get("spend", 0) or 0))
        insight_id = "ins_" + hashlib.sha256(
            f"account:{account.id}:{insight_date}".encode("utf-8")
        ).hexdigest()[:32]
        target = db.query(AccountInsight).filter(
            AccountInsight.ad_account_id == account.id,
            AccountInsight.date == insight_date,
        ).first()
        if not target:
            target = AccountInsight(
                id=insight_id,
                ad_account_id=account.id,
                date=insight_date,
            )
            db.add(target)

        impressions = int(row.get("impressions", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        target.spend = spend
        target.impressions = impressions
        target.clicks = clicks
        target.conversions = metrics["conversions"]
        target.link_clicks = metrics["link_clicks"]
        target.landing_page_views = metrics["landing_page_views"]
        target.leads = metrics["leads"]
        target.purchases = metrics["purchases"]
        target.complete_registrations = metrics["complete_registrations"]
        target.conversion_value = to_minor(metrics["conversion_value"])
        target.actions = row.get("actions") or []
        target.action_values = row.get("action_values") or []
        target.synced_at = datetime.utcnow()
        target.ctr = clicks / impressions if impressions else 0.0
        target.cpc = to_major(spend, account.currency) / clicks if clicks else 0.0
        target.cpm = to_major(spend, account.currency) / impressions * 1000 if impressions else 0.0
        target.extra_data = row
        count += 1
    return count

@router.post("/insights")
async def insights_callback(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(None), x_timestamp: str | None = Header(None), x_request_id: str | None = Header(None), x_idempotency_key: str | None = Header(None)):
    body = await request.body()
    headers = {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or "", "X-Request-Id": x_request_id or "", "X-Idempotency-Key": x_idempotency_key or ""}
    if not settings.SAAS_INTERNAL_SIGNING_KEY or not verify_request(settings.SAAS_INTERNAL_SIGNING_KEY, headers, "POST", "/api/v1/internal/fb-connector/insights", body):
        raise HTTPException(status_code=401, detail="invalid connector signature")
    payload = InsightsCallback.model_validate_json(body)
    logger.info(
        "[ConnectorInsightsCallback] received request_id=%s account_id=%s items=%s",
        payload.request_id,
        payload.account_id,
        len(payload.items),
    )
    # Callback 没有 SaaS JWT，必须先在禁用租户过滤的上下文里解析账户，
    # 再切换到该账户租户写入快照和 canonical Insights。
    with bypass_tenant():
        account = db.query(AdAccount).filter(
            or_(
                AdAccount.account_id == payload.account_id,
                AdAccount.account_id == _account_ref(payload.account_id),
            )
        ).first()
        meta = (
            db.query(MetaAccount).filter(MetaAccount.id == account.business_id).first()
            if account else None
        )
    expected_credential_id = (
        getattr(account, "connector_credential_id", None)
        or getattr(meta, "connector_credential_id", None)
    )
    if not account or not expected_credential_id or expected_credential_id != payload.credential_id:
        raise HTTPException(status_code=404, detail="Connector 账户或凭据不匹配")

    with tenant_scope(account.tenant_id):
        old = db.query(ConnectorInsightsSnapshot).filter(
            ConnectorInsightsSnapshot.request_id == payload.request_id
        ).first()
        if old:
            logger.info("[ConnectorInsightsCallback] duplicate request_id=%s", payload.request_id)
            return {"accepted": True, "duplicate": True, "request_id": payload.request_id}

        snapshot = ConnectorInsightsSnapshot(
            id=uuid.uuid4().hex,
            request_id=payload.request_id,
            credential_id=payload.credential_id,
            account_id=payload.account_id,
            days=payload.days,
            items=payload.items,
        )
        db.add(snapshot)
        count = _upsert_account_insights(db, account, payload.items)
        account.insights_sync_status = "SUCCESS"
        account.insights_last_synced_at = datetime.utcnow()
        account.insights_last_sync_error = None
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            duplicate = db.query(ConnectorInsightsSnapshot).filter(
                ConnectorInsightsSnapshot.request_id == payload.request_id
            ).first()
            if duplicate:
                logger.info("[ConnectorInsightsCallback] duplicate request_id=%s after race", payload.request_id)
                return {"accepted": True, "duplicate": True, "request_id": payload.request_id}
            raise

    logger.info(
        "[ConnectorInsightsCallback] stored request_id=%s account_id=%s rows=%s canonical=%s",
        payload.request_id,
        payload.account_id,
        len(payload.items),
        count,
    )
    return {
        "accepted": True,
        "duplicate": False,
        "account_id": payload.account_id,
        "count": len(payload.items),
        "canonical_count": count,
        "request_id": payload.request_id,
    }
