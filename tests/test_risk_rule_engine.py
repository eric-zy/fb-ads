from datetime import datetime, timedelta

from fastapi import Request

from api.risk_control import RiskRuleDryRunPayload, dry_run_risk_rule
from config.settings import settings
from models import AccountInsight, AdAccount, RiskExecution, RiskRule, Tenant, User, UserAccount
from services.risk_rule_engine import RiskRuleEngine, load_account_metrics


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345)})


def _account(db, account_id="engine-account"):
    account = AdAccount(
        id=account_id,
        tenant_id="test_tenant",
        account_id=f"act_{account_id}",
        account_name="规则引擎测试账户",
        currency="USD",
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    db.add(account)
    db.flush()
    return account


def test_engine_evaluates_and_or_and_uses_minor_unit_spend(db):
    account = _account(db)
    db.add(AccountInsight(
        id="engine-insight",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        date=datetime.utcnow().date(),
        spend=2500,
        impressions=1000,
        clicks=100,
        conversions=5,
    ))
    rule = RiskRule(
        id="engine-rule-and",
        tenant_id="test_tenant",
        name="Spend CTR",
        rule_type="quality",
        conditions=[
            {"metric": "spend", "operator": "gte", "value": 2000},
            {"metric": "ctr", "operator": "gte", "value": 5},
        ],
        logic="AND",
    )
    db.add(rule)
    db.commit()

    metrics = load_account_metrics(db, account)
    result = RiskRuleEngine(db).evaluate(rule, account.id, metrics=metrics)

    assert metrics["spend"] == 2500
    assert metrics["ctr"] == 10
    assert result["matched"] is True
    assert result["status"] == "MATCHED"


def test_engine_applies_scope_whitelist_minimums_and_cooldown(db):
    account = _account(db, "engine-guard-account")
    rule = RiskRule(
        id="engine-rule-guards",
        tenant_id="test_tenant",
        name="Guarded rule",
        rule_type="spend",
        conditions=[{"metric": "spend", "operator": "gt", "value": 1}],
        min_spend=1000,
        min_runtime=3600,
        cooldown_seconds=300,
        scope={"level": "ACCOUNT", "ids": [account.id]},
    )
    db.add(rule)
    db.commit()
    engine = RiskRuleEngine(db)

    assert engine.evaluate(rule, account.id, metrics={"spend": 999}, runtime_seconds=5000)["reason"] == "MIN_SPEND"
    assert engine.evaluate(rule, account.id, metrics={"spend": 1000}, runtime_seconds=100)["reason"] == "MIN_RUNTIME"

    rule.whitelist = [account.id]
    assert engine.evaluate(rule, account.id, metrics={"spend": 1000}, runtime_seconds=5000)["reason"] == "WHITELIST"
    rule.whitelist = []
    db.add(RiskExecution(
        id="engine-execution",
        tenant_id="test_tenant",
        run_id="run-1",
        rule_id=rule.id,
        ad_account_id=account.id,
        target_type="ACCOUNT",
        target_id=account.id,
        idempotency_key="recent-execution",
        status="MATCHED",
        created_at=datetime.utcnow() - timedelta(seconds=30),
    ))
    db.commit()
    assert engine.evaluate(rule, account.id, metrics={"spend": 1000}, runtime_seconds=5000)["reason"] == "COOLDOWN"


def test_engine_kill_switch_supports_global_and_tenant_settings(db, monkeypatch):
    account = _account(db, "engine-kill-account")
    rule = RiskRule(
        id="engine-rule-kill",
        tenant_id="test_tenant",
        name="Kill switch rule",
        rule_type="spend",
        conditions=[{"metric": "spend", "operator": "gt", "value": 1}],
    )
    db.add(rule)
    db.commit()
    monkeypatch.setattr(settings, "RISK_AUTOMATION_KILL_SWITCH", True)
    assert RiskRuleEngine(db).evaluate(rule, account.id, metrics={"spend": 100})["reason"] == "KILL_SWITCH"

    monkeypatch.setattr(settings, "RISK_AUTOMATION_KILL_SWITCH", False)
    tenant = db.query(Tenant).filter(Tenant.id == "test_tenant").one()
    tenant.settings = {"risk_control": {"kill_switch": True}}
    db.commit()
    assert RiskRuleEngine(db).evaluate(rule, account.id, metrics={"spend": 100})["reason"] == "KILL_SWITCH"


def test_dry_run_returns_local_metrics_and_evaluation(db):
    manager = User(
        id="engine-api-manager",
        tenant_id="test_tenant",
        email="engine-api-manager@test.local",
        username="engine-api-manager",
        hashed_password="unused",
        role="manager",
        permissions=[],
        is_active=True,
    )
    account = _account(db, "engine-api-account")
    db.add(UserAccount(
        id="engine-api-assignment",
        tenant_id="test_tenant",
        user_id=manager.id,
        account_id=account.id,
        assignment_status="ACTIVE",
    ))
    db.add(AccountInsight(
        id="engine-api-insight",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        date=datetime.utcnow().date(),
        spend=5000,
        impressions=1000,
        clicks=100,
    ))
    rule = RiskRule(
        id="engine-api-rule",
        tenant_id="test_tenant",
        name="Dry run rule",
        rule_type="spend",
        conditions=[{"metric": "spend", "operator": "gte", "value": 5000, "window_days": 7}],
    )
    db.add_all([manager, rule])
    db.commit()

    preview = dry_run_risk_rule(
        rule.id,
        RiskRuleDryRunPayload(account_ids=[account.id], window_days=1),
        request=_request(),
        current_user=manager,
        db=db,
    )

    assert preview["will_call_meta"] is False
    assert preview["conditions_evaluated"] == 1
    assert preview["matched_count"] == 1
    assert preview["window_days"] == 7
    assert preview["targets"][0]["metrics"]["spend"] == 5000
    assert preview["targets"][0]["evaluation"]["matched"] is True
