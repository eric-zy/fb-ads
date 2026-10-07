from datetime import timedelta
import pytest
from fastapi import HTTPException
from api.connector_callbacks_insights import _upsert_account_insights
from core.reporting_time import account_today
from models import AccountInsight, AdAccount, AuditLog, RevenueDailyTotal, User
from services.revenue import RevenueImport, import_revenue


def _setup(db):
    account = AdAccount(id="revenue-account", account_id="act_revenue", currency="USD")
    user = User(id="revenue-admin", tenant_id="test_tenant", role="tenant_admin")
    db.add(account)
    db.flush()
    day = account_today(account)
    db.add(AccountInsight(id="revenue-insight", ad_account_id=account.id, date=day, spend=10000))
    db.commit()
    return account, user, day


def _payload(account, day, revenue, source="manual", currency="USD"):
    return RevenueImport(records=[{"account_id": account.id, "date": day, "revenue": revenue,
                                   "source": source, "currency": currency}])


def test_daily_revenue_replaces_replay_and_adds_separate_sources(db):
    account, user, day = _setup(db)
    for _ in range(2):
        import_revenue(db, user, _payload(account, day, "200.00"))
    insight = db.query(AccountInsight).filter(AccountInsight.ad_account_id == account.id).one()
    assert insight.revenue == 20000
    assert insight.profit == 10000
    assert insight.roi == 1
    import_revenue(db, user, _payload(account, day, "50.00", source="partner"))
    import_revenue(db, user, _payload(account, day, "150.00"))
    assert insight.revenue == 20000
    assert db.query(RevenueDailyTotal).count() == 2
    assert db.query(AuditLog).filter(AuditLog.action == "IMPORT_REVENUE").count() == 4
    _upsert_account_insights(db, account, [{"date_start": str(day), "date_stop": str(day), "spend": "80.00"}])
    assert insight.revenue == 20000
    assert insight.profit == 12000
    assert insight.roi == 1.5


@pytest.mark.parametrize("amount,currency,offset", [("10.001", "USD", 0), ("10", "JPY", 0), ("10", "USD", 1)])
def test_invalid_revenue_import_is_rejected_without_writes(db, amount, currency, offset):
    account, user, day = _setup(db)
    with pytest.raises(HTTPException):
        import_revenue(db, user, _payload(account, day + timedelta(days=offset), amount, currency=currency))
    assert db.query(RevenueDailyTotal).count() == 0


def test_revenue_import_rejects_unassigned_users_and_duplicate_batch(db):
    account, _, day = _setup(db)
    user = User(id="revenue-unassigned", tenant_id="test_tenant", role="user")
    with pytest.raises(HTTPException) as error:
        import_revenue(db, user, _payload(account, day, "100"))
    assert error.value.status_code == 403
    user.role = "tenant_admin"
    record = _payload(account, day, "100").records[0]
    with pytest.raises(HTTPException) as error:
        import_revenue(db, user, RevenueImport(records=[record, record]))
    assert error.value.status_code == 400
    assert db.query(RevenueDailyTotal).count() == 0


def test_income_before_meta_sync_keeps_cost_and_freshness_unknown(db):
    from services.reporting import breakdown
    account = AdAccount(id="income-only-account", account_id="act_income_only", currency="USD")
    db.add(account)
    db.flush()
    admin = User(id="income-only-admin", tenant_id="test_tenant", role="tenant_admin")
    import_revenue(db, admin, _payload(account, account_today(account), "50"))
    row = db.query(AccountInsight).filter(AccountInsight.ad_account_id == account.id).one()
    assert row.spend is None
    assert row.synced_at is None
    assert row.profit is None
    assert row.roi is None
    report = breakdown(db, admin, "account", 1, account.id)
    assert report["items"][0]["revenue"] == 50
    assert report["items"][0]["spend"] is None
    from services.risk_rule_engine import RiskRuleEngine, load_account_metrics
    from models import RiskRule
    rule = RiskRule(id="income-only-risk", name="Income only", tenant_id="test_tenant", rule_type="spend",
                    is_active=True, conditions=[{"metric": "spend", "operator": "lt", "value": 100}])
    metrics = load_account_metrics(db, account)
    assert RiskRuleEngine(db).evaluate(rule, account.id, metrics=metrics)["reason"] == "DATA_UNAVAILABLE"
    _upsert_account_insights(db, account, [{"date_start": str(account_today(account)), "date_stop": str(account_today(account)), "spend": "10"}])
    assert row.profit == 4000
    assert row.roi == 4
