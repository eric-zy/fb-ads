"""工作台聚合接口：验证按用户可见广告账户隔离。"""

from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from api.workbench import workbench_summary
from models import AccountInsight, AdAccount, User, UserAccount


def test_workbench_summary_only_returns_assigned_accounts(db):
    user = User(
        id="workbench-user",
        tenant_id="test_tenant",
        email="workbench@test.local",
        username="workbench-user",
        hashed_password="unused",
        role="user",
        permissions=[],
        is_active=True,
    )
    visible = AdAccount(
        id="workbench-visible",
        tenant_id="test_tenant",
        account_id="act_visible",
        account_name="可见账户",
        currency="USD",
    )
    hidden = AdAccount(
        id="workbench-hidden",
        tenant_id="test_tenant",
        account_id="act_hidden",
        account_name="不可见账户",
        currency="USD",
    )
    db.add_all([user, visible, hidden])
    db.add(
        UserAccount(
            id="workbench-assignment",
            tenant_id="test_tenant",
            user_id=user.id,
            account_id=visible.id,
            assignment_status="ACTIVE",
        )
    )
    db.add_all([
        AccountInsight(
            id="workbench-insight-visible",
            tenant_id="test_tenant",
            ad_account_id=visible.id,
            date=date.today(),
            spend=1234,
            impressions=100,
            clicks=10,
            conversions=2,
            synced_at=datetime.utcnow(),
        ),
        AccountInsight(
            id="workbench-insight-hidden",
            tenant_id="test_tenant",
            ad_account_id=hidden.id,
            date=date.today(),
            spend=9999,
            impressions=900,
            clicks=90,
            conversions=9,
            synced_at=datetime.utcnow(),
        ),
    ])
    db.commit()

    payload = workbench_summary(db=db, current_user=user)

    assert payload["scope"]["account_count"] == 1
    assert payload["scope"]["accounts"][0]["id"] == visible.id
    assert payload["currency_totals"][0]["spend"] == 12.34
    assert payload["kpis"]["average_ctr"] == 10.0


def test_workbench_summary_rejects_unassigned_account(db):
    user = User(
        id="workbench-user-2",
        tenant_id="test_tenant",
        email="workbench-2@test.local",
        username="workbench-user-2",
        hashed_password="unused",
        role="user",
        permissions=[],
        is_active=True,
    )
    account = AdAccount(
        id="workbench-account-2",
        tenant_id="test_tenant",
        account_id="act_unassigned",
        account_name="未分配账户",
        currency="USD",
    )
    db.add_all([user, account])
    db.commit()

    with pytest.raises(HTTPException) as error:
        workbench_summary(account_id=account.id, db=db, current_user=user)

    assert error.value.status_code == 404


def test_workbench_summary_keeps_currency_totals_separate_and_reports_partial_staleness(db):
    user = User(
        id="workbench-user-3",
        tenant_id="test_tenant",
        email="workbench-3@test.local",
        username="workbench-user-3",
        hashed_password="unused",
        role="user",
        permissions=[],
        is_active=True,
    )
    usd = AdAccount(
        id="workbench-usd",
        tenant_id="test_tenant",
        account_id="act_usd",
        account_name="美元账户",
        currency="USD",
    )
    cny = AdAccount(
        id="workbench-cny",
        tenant_id="test_tenant",
        account_id="act_cny",
        account_name="人民币账户",
        currency="CNY",
    )
    db.add_all([user, usd, cny])
    db.add_all([
        UserAccount(id="workbench-assignment-usd", tenant_id="test_tenant", user_id=user.id, account_id=usd.id, assignment_status="ACTIVE"),
        UserAccount(id="workbench-assignment-cny", tenant_id="test_tenant", user_id=user.id, account_id=cny.id, assignment_status="ACTIVE"),
        AccountInsight(
            id="workbench-insight-usd",
            tenant_id="test_tenant",
            ad_account_id=usd.id,
            date=date.today(),
            spend=1000,
            impressions=100,
            clicks=10,
            synced_at=datetime.utcnow(),
        ),
        AccountInsight(
            id="workbench-insight-cny",
            tenant_id="test_tenant",
            ad_account_id=cny.id,
            date=date.today(),
            spend=2000,
            impressions=200,
            clicks=20,
            synced_at=datetime.utcnow() - timedelta(hours=4),
        ),
    ])
    db.commit()

    payload = workbench_summary(db=db, current_user=user)

    totals = {item["currency"]: item["spend"] for item in payload["currency_totals"]}
    assert totals == {"CNY": 20.0, "USD": 10.0}
    assert payload["freshness"]["status"] == "STALE"
    assert payload["freshness"]["stale_account_count"] == 1
    account_statuses = {item["id"]: item["freshness"]["status"] for item in payload["scope"]["accounts"]}
    assert account_statuses == {usd.id: "FRESH", cny.id: "STALE"}
