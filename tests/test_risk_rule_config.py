from models import RiskRule


def test_risk_rule_to_config_normalizes_legacy_nullable_fields():
    rule = RiskRule(
        id="risk-rule-1",
        name="Spend 无转化",
        rule_type="spend_anomaly",
        scope=None,
        conditions=None,
        logic=None,
        min_spend=None,
        min_runtime=None,
        cooldown_seconds=None,
        max_actions_per_run=None,
        dry_run=None,
        whitelist=None,
        priority=None,
        version=None,
    )

    config = rule.to_config()

    assert config["scope"] == {}
    assert config["conditions"] == []
    assert config["is_active"] is True
    assert config["logic"] == "AND"
    assert config["min_spend"] == 0
    assert config["min_runtime"] == 0
    assert config["cooldown_seconds"] == 0
    assert config["max_actions_per_run"] == 100
    assert config["dry_run"] is False
    assert config["whitelist"] == []
    assert config["priority"] == 0
    assert config["version"] == 1


def test_risk_rule_to_config_preserves_configured_values():
    rule = RiskRule(
        id="risk-rule-2",
        name="ROI",
        rule_type="roi",
        scope={"level": "campaign", "ids": ["cmp-1"]},
        conditions=[{"metric": "roi", "operator": "lt", "value": -0.3}],
        logic="or",
        min_spend=10000,
        min_runtime=3600,
        cooldown_seconds=7200,
        max_actions_per_run=5,
        dry_run=True,
        whitelist=[{"level": "campaign", "id": "cmp-safe"}],
        priority=10,
        version=3,
    )

    config = rule.to_config()

    assert config == {
        "id": "risk-rule-2",
        "name": "ROI",
        "description": None,
        "rule_type": "roi",
        "is_active": True,
        "scope": {"level": "campaign", "ids": ["cmp-1"]},
        "conditions": [{"metric": "roi", "operator": "lt", "value": -0.3}],
        "logic": "OR",
        "threshold": None,
        "threshold_unit": None,
        "min_spend": 10000,
        "min_runtime": 3600,
        "cooldown_seconds": 7200,
        "max_actions_per_run": 5,
        "dry_run": True,
        "whitelist": [{"level": "campaign", "id": "cmp-safe"}],
        "priority": 10,
        "version": 3,
    }
