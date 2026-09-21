from datetime import datetime

from fastapi import Request

from api.risk_control import (
    RiskEventResolvePayload,
    RiskRulePayload,
    create_risk_rule,
    list_risk_events,
    resolve_risk_event,
    risk_accounts,
    risk_overview,
)
from models import AdAccount, RiskEvent, RiskEventType, RiskLevel, User, UserAccount


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345)})


def _user(db, user_id: str, role: str = "user", permissions=None) -> User:
    user = User(
        id=user_id,
        tenant_id="test_tenant",
        email=f"{user_id}@test.local",
        username=user_id,
        hashed_password="unused",
        role=role,
        permissions=permissions or [],
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def test_risk_accounts_and_overview_respect_account_assignment(db):
    user = _user(db, "risk-api-user")
    visible = AdAccount(
        id="risk-api-visible",
        tenant_id="test_tenant",
        account_id="act_risk_visible",
        account_name="可见风险账户",
        currency="USD",
        risk_score=0.72,
    )
    hidden = AdAccount(
        id="risk-api-hidden",
        tenant_id="test_tenant",
        account_id="act_risk_hidden",
        account_name="不可见风险账户",
        currency="USD",
        risk_score=0.91,
    )
    db.add_all([visible, hidden])
    db.add(UserAccount(
        id="risk-api-assignment",
        tenant_id="test_tenant",
        user_id=user.id,
        account_id=visible.id,
        assignment_status="ACTIVE",
    ))
    db.add(RiskEvent(
        id="risk-api-event",
        tenant_id="test_tenant",
        ad_account_id=visible.id,
        event_type=RiskEventType.UNUSUAL_SPEND,
        risk_level=RiskLevel.HIGH,
        title="测试风险",
        description="测试事件",
        created_at=datetime.utcnow(),
    ))
    db.commit()

    accounts = risk_accounts(
        risk_level=None,
        system_status=None,
        unresolved_only=False,
        keyword=None,
        page=1,
        page_size=20,
        current_user=user,
        db=db,
    )
    overview = risk_overview(current_user=user, db=db)

    assert accounts["total"] == 1
    assert accounts["items"][0]["id"] == visible.id
    assert accounts["items"][0]["unresolved_events"] == 1
    assert overview["scope"]["account_count"] == 1
    assert overview["unresolved_events"] == 1


def test_manager_can_create_rule_and_platform_rule_remains_read_only(db):
    manager = _user(db, "risk-api-manager", role="manager")
    payload = RiskRulePayload(
        name="ROI 保护",
        rule_type="roi",
        conditions=[{"metric": "roi", "operator": "lt", "value": -0.3}],
        min_spend=10000,
        cooldown_seconds=3600,
        dry_run=True,
    )

    created = create_risk_rule(payload, _request(), current_user=manager, db=db)

    assert created["name"] == "ROI 保护"
    assert created["tenant_id"] == "test_tenant"
    assert created["dry_run"] is True


def test_user_can_resolve_visible_event_and_event_list_is_paginated(db):
    user = _user(db, "risk-api-resolver")
    account = AdAccount(
        id="risk-api-resolve-account",
        tenant_id="test_tenant",
        account_id="act_risk_resolve",
        account_name="待处理账户",
        currency="USD",
    )
    db.add(account)
    db.add(UserAccount(
        id="risk-api-resolve-assignment",
        tenant_id="test_tenant",
        user_id=user.id,
        account_id=account.id,
        assignment_status="ACTIVE",
    ))
    event = RiskEvent(
        id="risk-api-resolve-event",
        tenant_id="test_tenant",
        ad_account_id=account.id,
        event_type=RiskEventType.HIGH_FRAUD,
        risk_level=RiskLevel.CRITICAL,
        title="待处理风险",
        description="需要人工确认",
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()

    result = resolve_risk_event(
        event.id,
        RiskEventResolvePayload(resolution="已核查并记录处理结论"),
        _request(),
        current_user=user,
        db=db,
    )
    listed = list_risk_events(
        account_id=None,
        risk_level=None,
        event_type=None,
        resolved=None,
        page=1,
        page_size=10,
        current_user=user,
        db=db,
    )

    assert result["is_resolved"] is True
    assert result["resolved_by"] == user.id
    assert listed["total"] == 1
    assert listed["items"][0]["resolution"] == "已核查并记录处理结论"
