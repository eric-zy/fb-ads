"""广告账户消耗总览的日期窗口与金额汇总回归测试。"""

from datetime import date, timedelta, datetime

from api.reports import account_overview
from models import AccountInsight, AdAccount, User


def test_account_overview_defaults_to_recent_three_days(db):
    admin = User(
        id="reports-admin",
        tenant_id="test_tenant",
        email="reports-admin@test.local",
        username="reports-admin",
        hashed_password="unused",
        role="tenant_admin",
        is_active=True,
    )
    account = AdAccount(
        id="reports-account",
        tenant_id="test_tenant",
        account_id="act_reports",
        account_name="报表账户",
        currency="USD",
    )
    db.add_all([admin, account])
    db.add(AccountInsight(
        id="reports-insight-old-enough",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        date=date.today() - timedelta(days=2),
        spend=1234,
        impressions=100,
        clicks=10,
        synced_at=datetime.utcnow(),
    ))
    db.commit()

    payload = account_overview(start_date=None, end_date=None, db=db, current_user=admin)

    assert payload["start_date"] == str(date.today() - timedelta(days=2))
    assert payload["end_date"] == str(date.today())
    assert payload["items"][0]["spend"] == 12.34
    assert payload["currency_totals"][0]["spend"] == 12.34


def test_account_overview_shows_successful_sync_when_meta_returns_no_rows(db):
    admin = User(
        id="reports-empty-admin",
        tenant_id="test_tenant",
        email="reports-empty-admin@test.local",
        username="reports-empty-admin",
        hashed_password="unused",
        role="tenant_admin",
        is_active=True,
    )
    synced_at = datetime.utcnow()
    account = AdAccount(
        id="reports-empty-account",
        tenant_id="test_tenant",
        account_id="act_reports_empty",
        account_name="无消耗账户",
        currency="USD",
        insights_sync_status="SUCCESS",
        insights_last_synced_at=synced_at,
    )
    db.add_all([admin, account])
    db.commit()

    payload = account_overview(start_date=None, end_date=None, db=db, current_user=admin)

    item = payload["items"][0]
    assert item["spend"] == 0
    assert item["sync_status"] == "FRESH"
    assert item["latest_synced_at"] == synced_at.isoformat()


def test_account_overview_exposes_report_sync_failure(db):
    admin = User(
        id="reports-failed-admin",
        tenant_id="test_tenant",
        email="reports-failed-admin@test.local",
        username="reports-failed-admin",
        hashed_password="unused",
        role="tenant_admin",
        is_active=True,
    )
    account = AdAccount(
        id="reports-failed-account",
        tenant_id="test_tenant",
        account_id="act_reports_failed",
        account_name="同步失败账户",
        currency="USD",
        insights_sync_status="FAILED",
        insights_last_sync_error="Connector 超时",
    )
    db.add_all([admin, account])
    db.commit()

    payload = account_overview(start_date=None, end_date=None, db=db, current_user=admin)

    item = payload["items"][0]
    assert item["sync_status"] == "FAILED"
    assert item["sync_error"] == "Connector 超时"
