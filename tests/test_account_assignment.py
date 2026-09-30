"""主投手/协作者分配与账户操作租约。"""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from models import (
    AccountAssignmentRule,
    AdAccount,
    User,
    UserAccount,
)
from api.campaigns import _require_operation_leases
from api.accounts import _require_account_operation_lease, _require_sync_leases
from api.jobs import _require_submission_leases
from services.account_dispatch import AccountDispatchService
from services.account_operation_lease import (
    AccountOperationBusy,
    AccountOperationLeaseService,
)


def _user(db, user_id: str) -> User:
    row = User(
        id=user_id,
        tenant_id="test_tenant",
        email=f"{user_id}@test.local",
        username=user_id,
        hashed_password="unused",
        role="user",
        is_active=True,
    )
    db.add(row)
    return row


def test_dispatch_promotes_legacy_collaborator_and_keeps_single_primary(db):
    primary_candidate = _user(db, "assignment-user-a")
    other = _user(db, "assignment-user-b")
    account = AdAccount(
        id="assignment-account",
        tenant_id="test_tenant",
        account_id="act_assignment",
        account_name="分配测试账户",
    )
    db.add(account)
    db.add_all([
        UserAccount(
            id="assignment-row-a",
            tenant_id="test_tenant",
            user_id=primary_candidate.id,
            account_id=account.id,
            role="publisher",
            assignment_role="COLLABORATOR",
            assignment_status="ACTIVE",
        ),
        UserAccount(
            id="assignment-row-b",
            tenant_id="test_tenant",
            user_id=other.id,
            account_id=account.id,
            role="publisher",
            assignment_role="COLLABORATOR",
            assignment_status="ACTIVE",
        ),
    ])
    db.flush()

    row = AccountDispatchService(db).dispatch("test_tenant", account.id, "operator")

    assert row.user_id == primary_candidate.id
    rows = db.query(UserAccount).filter(UserAccount.account_id == account.id).all()
    assert [item.user_id for item in rows if item.assignment_role == "PRIMARY"] == [primary_candidate.id]


def test_dispatch_creates_primary_assignment_from_rule(db):
    user = _user(db, "assignment-user-rule")
    account = AdAccount(
        id="assignment-account-rule",
        tenant_id="test_tenant",
        account_id="act_assignment_rule",
        account_name="规则分配测试账户",
    )
    db.add(account)
    db.add(AccountAssignmentRule(
        id="assignment-rule",
        tenant_id="test_tenant",
        name="固定投手",
        target_user_id=user.id,
        priority="1",
        rule_type="FIXED_USER",
        rule_config={},
        status="ACTIVE",
    ))
    db.flush()

    row = AccountDispatchService(db).dispatch("test_tenant", account.id, "operator")

    assert row.user_id == user.id
    assert row.assignment_role == "PRIMARY"
    assert row.assignment_type == "AUTO"


def test_operation_lease_blocks_other_holder_and_allows_release(db):
    service = AccountOperationLeaseService(db)
    first = service.acquire("test_tenant", "lease-account", "user-a", "EDIT_TEMPLATE", 60)
    db.commit()

    with pytest.raises(AccountOperationBusy) as exc_info:
        service.acquire("test_tenant", "lease-account", "user-b", "EDIT_TEMPLATE", 60)
    assert exc_info.value.lease.holder_user_id == "user-a"

    assert service.release("test_tenant", "lease-account", "user-b", first.lease_token) is False
    assert service.release("test_tenant", "lease-account", "user-a", first.lease_token) is True
    db.commit()
    assert service.get("test_tenant", "lease-account") is None


def test_expired_operation_lease_can_be_reclaimed(db):
    service = AccountOperationLeaseService(db)
    lease = service.acquire("test_tenant", "lease-expired", "user-a", "SYNC", 60)
    lease.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    reclaimed = service.acquire("test_tenant", "lease-expired", "user-b", "SYNC", 60)
    db.commit()
    assert reclaimed.holder_user_id == "user-b"


def test_job_submission_requires_the_current_users_matching_lease(db):
    user = _user(db, "lease-submit-user")
    service = AccountOperationLeaseService(db)
    lease = service.acquire(
        "test_tenant",
        "lease-submit-account",
        user.id,
        "CAMPAIGN_CREATE",
        60,
    )
    db.commit()

    _require_submission_leases(
        db,
        user,
        ["lease-submit-account"],
        {"lease-submit-account": lease.lease_token},
        "CAMPAIGN_CREATE",
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_submission_leases(
            db,
            user,
            ["lease-submit-account"],
            {"lease-submit-account": "wrong-token"},
            "CAMPAIGN_CREATE",
        )
    assert exc_info.value.status_code == 409


def test_campaign_operation_requires_the_matching_operation_lease(db):
    user = _user(db, "campaign-lease-user")
    service = AccountOperationLeaseService(db)
    lease = service.acquire(
        "test_tenant",
        "campaign-lease-account",
        user.id,
        "CAMPAIGN_ACTION",
        60,
    )
    db.commit()

    _require_operation_leases(
        db,
        user,
        ["campaign-lease-account"],
        {"campaign-lease-account": lease.lease_token},
        "CAMPAIGN_ACTION",
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_operation_leases(
            db,
            user,
            ["campaign-lease-account"],
            {"campaign-lease-account": lease.lease_token},
            "CAMPAIGN_SYNC",
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "account_operation_lease_required"


def test_account_sync_requires_an_account_sync_lease(db):
    user = _user(db, "account-sync-lease-user")
    service = AccountOperationLeaseService(db)
    lease = service.acquire(
        "test_tenant",
        "account-sync-lease-account",
        user.id,
        "ACCOUNT_SYNC",
        60,
    )
    db.commit()

    _require_sync_leases(
        db,
        user,
        ["account-sync-lease-account"],
        {"account-sync-lease-account": lease.lease_token},
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_sync_leases(
            db,
            user,
            ["account-sync-lease-account"],
            {},
        )
    assert exc_info.value.status_code == 409


def test_account_mutation_and_assignment_require_their_own_lease_type(db):
    user = _user(db, "account-mutation-lease-user")
    account = AdAccount(
        id="account-mutation-lease-account",
        tenant_id="test_tenant",
        account_id="act_account_mutation",
        account_name="账户写操作租约测试",
    )
    db.add(account)
    service = AccountOperationLeaseService(db)
    lease = service.acquire(
        "test_tenant",
        account.id,
        user.id,
        "ACCOUNT_MUTATION",
        60,
    )
    db.commit()

    _require_account_operation_lease(
        db, user, account, lease.lease_token, "ACCOUNT_MUTATION"
    )

    with pytest.raises(HTTPException) as exc_info:
        _require_account_operation_lease(
            db, user, account, lease.lease_token, "ACCOUNT_ASSIGNMENT"
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["operation_type"] == "ACCOUNT_ASSIGNMENT"
