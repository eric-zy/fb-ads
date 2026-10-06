from datetime import date, datetime
from decimal import Decimal
import hashlib
import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, null

from core.money import to_minor, exponent_for
from core.reporting_time import account_today
from core.tenant import effective_tenant_id
from models import AccountInsight, AdAccount, AuditLog, RevenueDailyTotal
from services.account_access import accessible_account_ids


class RevenueRecord(BaseModel):
    account_id: str = Field(min_length=1, max_length=50)
    date: date
    source: str = Field(default="manual", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    currency: str = Field(min_length=3, max_length=16)
    revenue: Decimal = Field(max_digits=18, decimal_places=6, allow_inf_nan=False)


class RevenueImport(BaseModel):
    records: list[RevenueRecord] = Field(min_length=1, max_length=500)


def update_financial_metrics(insight):
    if not hasattr(insight, "revenue"):
        return
    if insight.revenue is None or insight.spend is None:
        insight.profit = insight.roi = None
    else:
        insight.profit = insight.revenue - (insight.spend or 0)
        insight.roi = insight.profit / insight.spend if insight.spend else None


def import_revenue(db, user, payload, request=None):
    tenant_id = effective_tenant_id(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="请先切换到目标租户")
    account_ids = sorted({item.account_id for item in payload.records})
    query = db.query(AdAccount).filter(AdAccount.tenant_id == tenant_id, AdAccount.id.in_(account_ids))
    if not user.is_admin():
        query = query.filter(AdAccount.id.in_(accessible_account_ids(db, user) or {"__none__"}))
    # Serialize imports for each account so separate sources cannot lose an update.
    accounts = {item.id: item for item in query.order_by(AdAccount.id).with_for_update().all()}
    if set(account_ids) != set(accounts):
        raise HTTPException(status_code=403, detail="部分广告账户不存在或无权导入收入")
    keys = set()
    for item in payload.records:
        account = accounts[item.account_id]
        key = (item.account_id, item.date, item.source)
        if key in keys:
            raise HTTPException(status_code=400, detail="同一批次包含重复的账户/日期/来源")
        keys.add(key)
        if item.currency.upper() != (account.currency or "USD").upper():
            raise HTTPException(status_code=400, detail="收入币种必须与广告账户币种一致")
        if item.date > account_today(account):
            raise HTTPException(status_code=400, detail="不能导入账户时区下未来日期的收入")
        scaled = item.revenue * (10 ** exponent_for(item.currency))
        if scaled != scaled.to_integral_value():
            raise HTTPException(status_code=400, detail="收入金额精度超出账户币种允许的小数位")
        if abs(scaled) > 2 ** 63 - 1:
            raise HTTPException(status_code=400, detail="收入金额超出存储范围")
    results = []
    for item in payload.records:
        entry = db.query(RevenueDailyTotal).filter(
            RevenueDailyTotal.ad_account_id == item.account_id, RevenueDailyTotal.date == item.date,
            RevenueDailyTotal.source == item.source,
        ).first()
        old = entry.revenue if entry else None
        if not entry:
            entry = RevenueDailyTotal(id=uuid.uuid4().hex, ad_account_id=item.account_id, date=item.date, source=item.source)
            db.add(entry)
        entry.currency, entry.revenue, entry.updated_by = item.currency.upper(), to_minor(item.revenue, item.currency), user.id
        entry.updated_at = datetime.utcnow()
        db.flush()
        income = db.query(func.sum(RevenueDailyTotal.revenue)).filter(
            RevenueDailyTotal.ad_account_id == item.account_id, RevenueDailyTotal.date == item.date,
        ).scalar()
        if abs(income) > 2 ** 63 - 1:
            raise HTTPException(status_code=400, detail="收入合计超出存储范围")
        insight = db.query(AccountInsight).filter(AccountInsight.ad_account_id == item.account_id, AccountInsight.date == item.date).first()
        if not insight:
            digest = hashlib.sha256(f"account:{item.account_id}:{item.date}".encode()).hexdigest()[:32]
            # Income is independent of the Meta snapshot; an unknown cost must
            # not appear as zero or make the imported revenue look like profit.
            insight = AccountInsight(id="ins_" + digest, ad_account_id=item.account_id, date=item.date,
                                     spend=null(), synced_at=null())
            db.add(insight)
            db.flush()
        insight.revenue = int(income)
        update_financial_metrics(insight)
        db.add(AuditLog(id=uuid.uuid4().hex, user_id=user.id, action="IMPORT_REVENUE",
                        resource_type="revenue_daily_total", resource_id=entry.id,
                        request_data={"account_id": item.account_id, "date": str(item.date), "source": item.source,
                                      "currency": entry.currency, "previous_revenue_minor": old, "revenue_minor": entry.revenue},
                        ip_address=request.client.host if request and request.client else None))
        results.append({"account_id": item.account_id, "date": str(item.date), "source": item.source,
                        "currency": entry.currency, "revenue_minor": insight.revenue,
                        "profit_minor": insight.profit, "roi": insight.roi})
    db.commit()
    return {"count": len(results), "items": results, "mode": "REPLACE_DAILY_SOURCE_TOTAL"}
