from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from core.money import to_minor
from core.reporting_time import account_today
from api.reports import report_breakdown, report_trend
from models import User, AdAccount, Campaign, AdGroup, Ad, AdInsight, AccountInsight


def _admin():
    return User(id="report-accuracy-admin", role="tenant_admin", tenant_id="test_tenant")


def test_ad_trend_with_data_and_no_financial_fields(db):
    account = AdAccount(id="ad-trend-account", account_id="act_ad_trend", currency="JPY")
    campaign = Campaign(id="ad-trend-campaign", campaign_id="remote-c", ad_account_id=account.id, name="Campaign")
    group = AdGroup(id="ad-trend-group", ad_group_id="remote-g", campaign_id=campaign.id, name="Group")
    ad = Ad(id="ad-trend-ad", ad_id="remote-a", ad_group_id=group.id, name="Ad")
    db.add_all([account, campaign, group, ad])
    db.flush()
    db.add(AdInsight(id="ad-trend-insight", ad_id=ad.id, date=account_today(account), spend=1000,
                     impressions=100, clicks=10, conversions=2, conversion_value=2000))
    db.commit()
    payload = report_trend(dimension="ad", entity_id=ad.id, days=1, db=db, current_user=_admin())
    assert payload["total"]["spend"] == 1000
    assert payload["total"]["roi"] is None
    assert payload["total"]["revenue"] is None
    assert payload["total"]["roas"] == 2


def test_report_window_and_currency_totals(db):
    for currency in ("USD", "JPY"):
        account = AdAccount(id="accuracy-" + currency, account_id="act_accuracy_" + currency, currency=currency)
        db.add(account)
        db.flush()
        today = account_today(account)
        for offset in (0, 1, -1):
            db.add(AccountInsight(id=f"accuracy-{currency}-{offset}", ad_account_id=account.id,
                                  date=today - timedelta(days=offset), spend=1000, clicks=1, revenue=None))
    db.commit()
    payload = report_trend(dimension="account", days=1, entity_id=None, db=db, current_user=_admin())
    assert payload["data_quality"]["row_count"] == 2
    assert payload["total"]["spend"] is None
    assert {item["currency"]: item["spend"] for item in payload["currency_totals"]} == {"USD": 10, "JPY": 1000}
    items = report_breakdown(dimension="account", days=1, parent_id=None, db=db, current_user=_admin())["items"]
    assert {item["currency"]: item["spend"] for item in items} == {"USD": 10, "JPY": 1000}
    assert all(item["roi"] is None for item in items)


def test_trend_rejects_unassigned_account(db):
    db.add(AdAccount(id="private-report-account", account_id="act_private_report", currency="USD"))
    db.commit()
    user = User(id="unassigned-report-user", tenant_id="test_tenant", role="user")
    with pytest.raises(HTTPException) as error:
        report_trend(dimension="account", entity_id="private-report-account", days=1, db=db, current_user=user)
    assert error.value.status_code == 403


def test_timezone_day_and_decimal_money_conversion():
    account = AdAccount(timezone="America/Los_Angeles")
    assert str(account_today(account, datetime(2026, 10, 6, 1, tzinfo=timezone.utc))) == "2026-10-05"
    assert to_minor("90071992547409.93", "USD") == 9007199254740993
