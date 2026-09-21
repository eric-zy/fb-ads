from datetime import datetime, timedelta

from config.settings import settings
from models import AdAccount, AccountInsight, Campaign, CampaignInsight, CampaignStatus, DeliveryAction, RiskExecution, RiskEvent, RiskRule
from services.risk_action_service import retry_failed_execution, run_account_rules


class _FakeConnector:
    calls = []
    should_fail = False

    def pause_campaign(self, campaign_id, credential_id, *, idempotency_key=None, **kwargs):
        self.calls.append((campaign_id, credential_id, idempotency_key))
        if self.should_fail:
            raise RuntimeError("模拟 Meta 暂停失败")
        return {"remote": "PAUSED", "campaign_id": campaign_id}


def _fixture(db):
    account = AdAccount(
        id="risk-action-account",
        tenant_id="test_tenant",
        account_id="act_risk_action",
        account_name="动作测试账户",
        currency="USD",
        connector_credential_id="connector-credential",
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    campaign = Campaign(
        id="risk-action-campaign",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        campaign_id="meta-risk-action-campaign",
        name="需要暂停的系列",
        status=CampaignStatus.ACTIVE,
    )
    insight = AccountInsight(
        id="risk-action-insight",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        date=datetime.utcnow().date(),
        spend=5000,
        impressions=1000,
        clicks=100,
    )
    rule = RiskRule(
        id="risk-action-rule",
        tenant_id="test_tenant",
        name="高花费保护",
        rule_type="spend",
        conditions=[{"metric": "spend", "operator": "gte", "value": 5000}],
        action_on_trigger="PAUSE_CAMPAIGN",
        max_actions_per_run=1,
        cooldown_seconds=300,
    )
    db.add_all([account, campaign, insight, rule])
    db.commit()
    return account, campaign, rule


def test_risk_action_calls_meta_before_local_campaign_pause(db, monkeypatch):
    account, campaign, rule = _fixture(db)
    _FakeConnector.calls = []
    _FakeConnector.should_fail = False
    monkeypatch.setattr("services.risk_action_service.FBConnectorClient", _FakeConnector)

    result = run_account_rules(db, account, run_id="risk-run-success")

    db.refresh(campaign)
    execution = db.query(RiskExecution).filter(RiskExecution.rule_id == rule.id).one()
    delivery = db.query(DeliveryAction).one()
    assert result["counts"]["success"] == 1
    assert campaign.status == CampaignStatus.PAUSED
    assert _FakeConnector.calls[0][0] == campaign.campaign_id
    assert delivery.status == "SUCCESS"
    assert execution.status == "SUCCESS"
    assert db.query(RiskEvent).filter(RiskEvent.ad_account_id == account.id).count() == 1

    # 同一规则、目标和数据窗口再次执行会被 cooldown/幂等保护拦截，不重复调用 Meta。
    result_again = run_account_rules(db, account, run_id="risk-run-repeat")
    assert result_again["counts"]["skipped"] == 1
    assert len(_FakeConnector.calls) == 1


def test_risk_action_failure_does_not_mark_campaign_paused(db, monkeypatch):
    account, campaign, rule = _fixture(db)
    _FakeConnector.calls = []
    _FakeConnector.should_fail = True
    monkeypatch.setattr("services.risk_action_service.FBConnectorClient", _FakeConnector)

    result = run_account_rules(db, account, run_id="risk-run-failure")

    db.refresh(campaign)
    execution = db.query(RiskExecution).filter(RiskExecution.rule_id == rule.id).one()
    delivery = db.query(DeliveryAction).one()
    assert result["counts"]["failed"] == 1
    assert campaign.status == CampaignStatus.ACTIVE
    assert delivery.status == "FAILED"
    assert execution.status == "FAILED"
    assert execution.retry_count == 1
    assert "模拟 Meta 暂停失败" in execution.error_message


def test_failed_execution_can_be_explicitly_retried(db, monkeypatch):
    account, campaign, rule = _fixture(db)
    _FakeConnector.calls = []
    _FakeConnector.should_fail = True
    monkeypatch.setattr("services.risk_action_service.FBConnectorClient", _FakeConnector)
    run_account_rules(db, account, run_id="risk-run-retry-1")

    _FakeConnector.should_fail = False
    execution = db.query(RiskExecution).filter(RiskExecution.rule_id == rule.id).one()
    retried = retry_failed_execution(db, execution)

    db.refresh(campaign)
    assert retried.status == "SUCCESS"
    assert campaign.status == CampaignStatus.PAUSED
    assert len(_FakeConnector.calls) == 2


def test_campaign_scope_uses_campaign_insights_and_target_id(db, monkeypatch):
    account, campaign, rule = _fixture(db)
    rule.scope = {"level": "CAMPAIGN", "ids": [campaign.id]}
    db.add(CampaignInsight(
        id="risk-action-campaign-insight",
        tenant_id="test_tenant",
        campaign_id=campaign.id,
        date=datetime.utcnow().date(),
        spend=5000,
        impressions=1000,
        clicks=100,
    ))
    db.commit()
    _FakeConnector.calls = []
    _FakeConnector.should_fail = False
    monkeypatch.setattr("services.risk_action_service.FBConnectorClient", _FakeConnector)

    run_account_rules(db, account, run_id="risk-run-campaign-scope")

    execution = db.query(RiskExecution).filter(RiskExecution.rule_id == rule.id).one()
    assert execution.target_type == "CAMPAIGN"
    assert execution.target_id == campaign.id
    assert campaign.status == CampaignStatus.PAUSED


def test_dry_run_rule_never_calls_meta_or_changes_local_status(db, monkeypatch):
    account, campaign, rule = _fixture(db)
    rule.dry_run = True
    db.commit()
    _FakeConnector.calls = []
    _FakeConnector.should_fail = False
    monkeypatch.setattr("services.risk_action_service.FBConnectorClient", _FakeConnector)

    result = run_account_rules(db, account, run_id="risk-run-dry-run")

    db.refresh(campaign)
    execution = db.query(RiskExecution).filter(RiskExecution.rule_id == rule.id).one()
    assert result["counts"]["skipped"] == 1
    assert execution.status == "SKIPPED"
    assert execution.mode == "DRY_RUN"
    assert execution.provider_response["reason"] == "DRY_RUN"
    assert campaign.status == CampaignStatus.ACTIVE
    assert _FakeConnector.calls == []
    assert db.query(DeliveryAction).count() == 0
