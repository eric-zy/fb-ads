"""Permission-scoped report aggregation with explicit currency and missing data."""
from datetime import timedelta

from fastapi import HTTPException

from core.money import to_major
from core.reporting_time import account_today
from core.tenant import effective_tenant_id
from models import AccountInsight, CampaignInsight, AdSetInsight, AdInsight, AdAccount, Campaign, AdGroup, Ad
from services.account_access import accessible_account_ids


COUNTS = ("impressions", "clicks", "conversions", "link_clicks", "landing_page_views", "leads", "purchases")
MONEY = ("spend", "conversion_value", "revenue", "profit")


def report_rows(db, user, dimension, days, entity_id=None, parent_id=None):
    models = {"account": (AccountInsight, "ad_account_id"), "campaign": (CampaignInsight, "campaign_id"),
              "adset": (AdSetInsight, "ad_group_id"), "ad": (AdInsight, "ad_id")}
    if dimension not in models:
        raise HTTPException(status_code=400, detail="不支持的报表维度")
    query = db.query(AdAccount)
    tenant_id = effective_tenant_id(user)
    if tenant_id:
        query = query.filter(AdAccount.tenant_id == tenant_id)
    if not user.is_admin():
        query = query.filter(AdAccount.id.in_(accessible_account_ids(db, user) or {"__none__"}))
    accounts = {account.id: account for account in query.all()}
    if dimension == "account":
        entities = {key: (account.account_name or account.account_id, account) for key, account in accounts.items()
                    if not parent_id or key == parent_id}
    else:
        campaigns = {item.id: item for item in db.query(Campaign).filter(Campaign.ad_account_id.in_(accounts)).all()}
        if dimension == "campaign":
            entities = {key: (item.name, accounts[item.ad_account_id]) for key, item in campaigns.items()
                        if not parent_id or item.ad_account_id == parent_id}
        else:
            groups = {item.id: item for item in db.query(AdGroup).filter(AdGroup.campaign_id.in_(campaigns)).all()}
            if dimension == "adset":
                entities = {key: (item.name, accounts[campaigns[item.campaign_id].ad_account_id]) for key, item in groups.items()
                            if not parent_id or item.campaign_id == parent_id}
            else:
                ads = db.query(Ad).filter(Ad.ad_group_id.in_(groups)).all()
                entities = {item.id: (item.name, accounts[campaigns[groups[item.ad_group_id].campaign_id].ad_account_id])
                            for item in ads if not parent_id or item.ad_group_id == parent_id}
    if entity_id:
        if entity_id not in entities:
            raise HTTPException(status_code=404 if user.is_admin() else 403, detail="报表对象不存在或无权访问")
        entities = {entity_id: entities[entity_id]}
    if not entities:
        return [], entities
    windows = {}
    for key, (_, account) in entities.items():
        end = account_today(account)
        windows[key] = (end - timedelta(days=days - 1), end)
    model, foreign_key = models[dimension]
    rows = db.query(model).filter(
        getattr(model, foreign_key).in_(entities),
        model.date >= min(start for start, _ in windows.values()),
        model.date <= max(end for _, end in windows.values()),
    ).order_by(model.date.asc()).all()
    return [(row, getattr(row, foreign_key)) for row in rows
            if windows[getattr(row, foreign_key)][0] <= row.date <= windows[getattr(row, foreign_key)][1]], entities


def aggregate_metrics(rows, currency):
    result = {field: sum(getattr(row, field, 0) or 0 for row in rows) for field in COUNTS}
    for field in MONEY:
        values = [getattr(row, field, None) for row in rows]
        available = (field == "spend" and not rows) or bool(rows) and all(value is not None for value in values)
        result[field] = to_major(sum(value or 0 for value in values), currency) if available else None
    spend, clicks, impressions = result["spend"], result["clicks"], result["impressions"]
    result.update(
        currency=currency,
        ctr=clicks / impressions * 100 if impressions else 0,
        conversion_rate=result["conversions"] / clicks * 100 if clicks else 0,
        cpc=spend / clicks if clicks and spend is not None else None,
        cpm=spend / impressions * 1000 if impressions and spend is not None else None,
        cpa=spend / result["conversions"] if result["conversions"] and spend is not None else None,
        roas=result["conversion_value"] / spend if spend and result["conversion_value"] is not None else None,
        revenue_roas=result["revenue"] / spend if spend and result["revenue"] is not None else None,
        roi=(result["revenue"] - spend) / spend if spend and result["revenue"] is not None else None,
    )
    return result


def breakdown(db, user, dimension, days, parent_id):
    rows, entities = report_rows(db, user, dimension, days, parent_id=parent_id)
    grouped = {}
    for row, key in rows:
        grouped.setdefault(key, []).append(row)
    items = [{"entity_id": key, "entity_name": entities[key][0],
              **aggregate_metrics(values, entities[key][1].currency or "USD")} for key, values in grouped.items()]
    return {"dimension": dimension, "days": days, "parent_id": parent_id,
            "items": sorted(items, key=lambda item: item["spend"] or 0, reverse=True)}


def trend(db, user, dimension, days, entity_id):
    rows, entities = report_rows(db, user, dimension, days, entity_id=entity_id)
    daily, currencies = {}, {}
    for row, key in rows:
        currency = entities[key][1].currency or "USD"
        daily.setdefault((row.date, currency), []).append(row)
        currencies.setdefault(currency, []).append(row)
    series = [{"date": str(day), **aggregate_metrics(values, currency)}
              for (day, currency), values in sorted(daily.items())]
    currency_totals = [aggregate_metrics(values, currency) for currency, values in sorted(currencies.items())]
    if len(currency_totals) == 1:
        total = currency_totals[0]
    else:
        # Counts remain additive; money/ratios cannot be summed across currencies.
        total = {field: sum(item[field] for item in currency_totals) for field in COUNTS}
        total.update({field: None for field in (*MONEY, "cpc", "cpm", "cpa", "roas", "revenue_roas", "roi")})
        total.update(currency=None, ctr=total["clicks"] / total["impressions"] * 100 if total["impressions"] else 0,
                     conversion_rate=total["conversions"] / total["clicks"] * 100 if total["clicks"] else 0)
    synced = [row.synced_at for row, _ in rows if row.synced_at]
    return {"dimension": dimension, "entity_id": entity_id, "days": days, "total": total,
            "series": series, "currency_totals": currency_totals,
            "currency_note": "不同币种未进行汇率换算，currency_totals 分组展示",
            "data_quality": {"row_count": len(rows), "latest_synced_at": max(synced).isoformat() if synced else None,
                             "has_data": bool(rows)}}
