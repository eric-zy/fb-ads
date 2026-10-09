"""Bulk assignment keeps per-account ownership, delegation and transaction boundaries."""
from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from models import AdAccount, User, UserAccount, MetaConnection, MetaConnectionAsset, AuditLog, Tenant
from services.bulk_account_assignment import (
    BulkAssignmentRequest, BulkAssignmentSubmit, AssignmentContextRequest,
    assignment_context, assignment_preview, assignment_submit,
)
from services.account_operation_lease import AccountOperationLeaseService


@pytest.fixture
def setup_bulk():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    db.add(Tenant(id="test_tenant", name="Bulk test", slug="bulk-test"))
    owner = User(id="owner", username="Original owner", email="owner@bulk.local", hashed_password="unused", role="tenant_admin", is_active=True)
    publisher = User(id="publisher", username="Publisher", email="publisher@bulk.local", hashed_password="unused", role="user", is_active=True)
    connection = MetaConnection(id="connection", meta_user_id="fb-owner", app_id="app", access_mode="connector",
        credential_id="opaque", authorized_by_user_id=owner.id, status="ACTIVE", scopes=["ads_management", "ads_read"])
    accounts = [AdAccount(id=f"account-{i}", account_id=f"act_{i}", account_name=f"Account {i}") for i in range(2)]
    db.add_all([owner, publisher, connection, *accounts]); db.flush()
    for account in accounts:
        db.add(UserAccount(id=f"original-{account.id}", user_id=owner.id, account_id=account.id, role="publisher", assignment_status="ACTIVE", assignment_role="PRIMARY"))
        db.add(MetaConnectionAsset(id=f"grant-{account.id}", connection_id=connection.id, asset_type="AD_ACCOUNT", asset_id=account.id, status="ACTIVE"))
    db.commit()
    yield db, owner, publisher, connection, accounts
    db.close(); engine.dispose()


def request_for(setup, **fields):
    _, _, publisher, connection, accounts = setup
    data = {"account_ids": [a.id for a in accounts], "user_ids": [publisher.id],
        "execution_mode": "DELEGATED", "execution_connection_id": connection.id}
    data.update(fields)
    return BulkAssignmentRequest(**data)


def submit_preview(setup, request, *, key=None, hashes=None):
    db, owner, *_ = setup
    preview = assignment_preview(db, owner, request)
    return assignment_submit(db, owner, BulkAssignmentSubmit(**request.model_dump(), idempotency_key=key or str(uuid.uuid4()),
        preview_hashes=hashes or {x["account_id"]: x.get("preview_hash", "") for x in preview["items"]}))


def test_bulk_collaboration_preserves_owner_and_warns_missing_page(setup_bulk):
    db, owner, publisher, connection, accounts = setup_bulk
    request = request_for(setup_bulk)
    context = assignment_context(db, owner, AssignmentContextRequest(account_ids=request.account_ids))
    assert len(context["items"]) == 2 and all(x["candidates"][0]["connection_id"] == connection.id for x in context["items"])
    preview = assignment_preview(db, owner, request)
    assert preview["ready_count"] == 2 and all("Page" in x["warnings"][0] for x in preview["items"])
    result = submit_preview(setup_bulk, request)
    assert result["success_count"] == 2
    for account in accounts:
        rows = db.query(UserAccount).filter_by(account_id=account.id).all()
        assert next(x.user_id for x in rows if x.assignment_role == "PRIMARY") == owner.id
        assert next(x for x in rows if x.user_id == publisher.id).execution_connection_id == connection.id
    assert connection.authorized_by_user_id == owner.id and db.query(AuditLog).count() == 2


def test_primary_transfer_keeps_original_as_collaborator(setup_bulk):
    db, owner, publisher, _, accounts = setup_bulk
    request = request_for(setup_bulk, action="PRIMARY", primary_user_id=publisher.id, execution_mode="KEEP")
    preview = assignment_preview(db, owner, request)
    assert all(x["old_primary_label"] == owner.username and x["primary_label"] == publisher.username for x in preview["items"])
    assert submit_preview(setup_bulk, request)["success_count"] == 2
    for account in accounts:
        assert db.query(UserAccount).filter_by(account_id=account.id, assignment_role="PRIMARY").one().user_id == publisher.id
        assert db.query(UserAccount).filter_by(account_id=account.id, user_id=owner.id).one().assignment_role == "COLLABORATOR"


def test_execution_only_requires_existing_assignment_and_never_adds_users(setup_bulk):
    db, _, publisher, connection, accounts = setup_bulk
    request = request_for(setup_bulk, action="EXECUTION")
    result = submit_preview(setup_bulk, request)
    assert result["failed_count"] == 2 and db.query(UserAccount).filter_by(user_id=publisher.id).count() == 0
    submit_preview(setup_bulk, request_for(setup_bulk))
    result = submit_preview(setup_bulk, request_for(setup_bulk, action="EXECUTION", execution_mode="PERSONAL"))
    assert result["success_count"] == 2
    for account in accounts:
        assert db.query(UserAccount).filter_by(account_id=account.id, user_id=publisher.id).one().execution_connection_id is None
    assert connection.status == "ACTIVE"


def test_success_replay_is_persisted_and_configuration_conflict_is_rejected(setup_bulk):
    db, *_ = setup_bulk
    request = request_for(setup_bulk)
    key = str(uuid.uuid4())
    result = submit_preview(setup_bulk, request, key=key)
    replay = submit_preview(setup_bulk, request, key=key)
    assert result["success_count"] == replay["success_count"] == 2 and all(x["replayed"] for x in replay["items"])
    assert db.query(AuditLog).count() == 2 and db.query(UserAccount).count() == 4
    changed = submit_preview(setup_bulk, request_for(setup_bulk, execution_mode="PERSONAL"), key=key)
    assert changed["failed_count"] == 2 and "配置不同" in changed["items"][0]["error"]


@pytest.mark.parametrize("change", ["assignment", "owner_disabled", "connection_expired", "grant_revoked", "user_disabled"])
def test_changed_preview_never_grants_stale_permission(setup_bulk, change):
    db, owner, publisher, connection, accounts = setup_bulk
    request = request_for(setup_bulk)
    preview = assignment_preview(db, owner, request)
    if change == "assignment": db.query(UserAccount).filter_by(account_id=accounts[0].id).one().role = "viewer"
    if change == "owner_disabled": owner.is_active = False
    if change == "connection_expired": connection.expires_at = datetime.utcnow() - timedelta(seconds=1)
    if change == "grant_revoked": db.query(MetaConnectionAsset).filter_by(asset_id=accounts[0].id).one().status = "REVOKED"
    if change == "user_disabled": publisher.is_active = False
    db.commit()
    result = assignment_submit(db, owner, BulkAssignmentSubmit(**request.model_dump(), idempotency_key=str(uuid.uuid4()),
        preview_hashes={x["account_id"]: x["preview_hash"] for x in preview["items"]}))
    assert result["items"][0]["status"] == "FAILED"
    assert db.query(UserAccount).filter_by(account_id=accounts[0].id, user_id=publisher.id).count() == 0


@pytest.mark.parametrize("holder", ["other-user", "owner"])
def test_busy_account_does_not_block_others_and_retry_uses_same_snapshot(setup_bulk, holder):
    db, owner, _, _, accounts = setup_bulk
    request = request_for(setup_bulk)
    preview = assignment_preview(db, owner, request)
    service = AccountOperationLeaseService(db)
    lease = service.acquire(owner.tenant_id, accounts[0].id, holder, "CAMPAIGN_CREATE", 120)
    token = lease.lease_token
    db.commit()
    payload = BulkAssignmentSubmit(**request.model_dump(), idempotency_key=str(uuid.uuid4()),
        preview_hashes={x["account_id"]: x["preview_hash"] for x in preview["items"]})
    result = assignment_submit(db, owner, payload)
    assert result["failed_count"] == result["success_count"] == 1
    assert result["items"][0]["account_name"] == accounts[0].account_name
    assert service.get(owner.tenant_id, accounts[0].id).lease_token == token
    service.release(owner.tenant_id, accounts[0].id, holder, token); db.commit()
    retry = payload.model_copy(update={"account_ids": [accounts[0].id]})
    assert assignment_submit(db, owner, retry)["success_count"] == 1
    assert db.query(AuditLog).count() == 2


def test_per_account_override_and_keep_existing_delegation(setup_bulk):
    db, owner, publisher, original, accounts = setup_bulk
    submit_preview(setup_bulk, request_for(setup_bulk))
    other = MetaConnection(id="other", meta_user_id="fb-other", app_id="app", access_mode="connector", credential_id="opaque-other",
        authorized_by_user_id=owner.id, status="ACTIVE", scopes=["ads_management", "ads_read"])
    db.add(other); db.flush()
    db.add(MetaConnectionAsset(id="other-grant", connection_id=other.id, asset_type="AD_ACCOUNT", asset_id=accounts[1].id, status="ACTIVE")); db.commit()
    request = request_for(setup_bulk, execution_overrides={accounts[1].id: other.id})
    assert submit_preview(setup_bulk, request)["success_count"] == 2
    assert db.query(UserAccount).filter_by(account_id=accounts[1].id, user_id=publisher.id).one().execution_connection_id == original.id
    request = request_for(setup_bulk, execution_overrides={accounts[1].id: other.id}, preserve_existing_execution=False)
    assert submit_preview(setup_bulk, request)["success_count"] == 2
    assert db.query(UserAccount).filter_by(account_id=accounts[1].id, user_id=publisher.id).one().execution_connection_id == other.id


def test_keep_does_not_restore_expired_delegation(setup_bulk):
    db, _, publisher, _, accounts = setup_bulk
    submit_preview(setup_bulk, request_for(setup_bulk))
    row = db.query(UserAccount).filter_by(user_id=publisher.id, account_id=accounts[0].id).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    assert submit_preview(setup_bulk, request_for(setup_bulk, execution_mode="KEEP"))["success_count"] == 2
    assert row.execution_connection_id is None and row.execution_granted_by is None


def test_cross_tenant_targets_cannot_be_granted_or_exposed(setup_bulk):
    from core.tenant import bypass_tenant
    db, owner, publisher, _, accounts = setup_bulk
    with bypass_tenant():
        other = AdAccount(id="other-account", tenant_id="other-tenant", account_id="act_foreign", account_name="Hidden name")
        db.add(other); db.commit()
    request = request_for(setup_bulk, account_ids=[accounts[0].id, other.id])
    with bypass_tenant():
        context = assignment_context(db, owner, request)
        result = submit_preview(setup_bulk, request)
    assert context["items"][1]["candidates"] == [] and context["items"][1]["account_name"] != other.account_name
    assert result["success_count"] == result["failed_count"] == 1
    assert db.query(UserAccount).filter_by(user_id=publisher.id, account_id=other.id).count() == 0


def test_save_failure_rolls_back_assignment_and_audit_per_account(setup_bulk, monkeypatch):
    db, _, publisher, _, accounts = setup_bulk
    real_commit = db.commit
    attempts = 0
    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1: raise RuntimeError("simulated commit failure")
        real_commit()
    monkeypatch.setattr(db, "commit", fail_once)
    result = submit_preview(setup_bulk, request_for(setup_bulk))
    assert result["success_count"] == result["failed_count"] == 1
    assert db.query(UserAccount).filter_by(account_id=accounts[0].id, user_id=publisher.id).count() == 0
    assert db.query(AuditLog).count() == 1


@pytest.mark.parametrize("endpoint", ["context", "preview", "submit"])
def test_bulk_routes_reject_ordinary_users(setup_bulk, endpoint):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.accounts import router
    from core.auth import get_current_active_user
    app = FastAPI()
    app.include_router(router)
    from core.database import get_db
    db, _, publisher, _, _ = setup_bulk
    overrides = dict(app.dependency_overrides)
    try:
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_active_user] = lambda: publisher
        payload = request_for(setup_bulk).model_dump()
        if endpoint == "submit": payload.update(idempotency_key=str(uuid.uuid4()), preview_hashes={})
        response = TestClient(app).post(f"/api/v1/accounts/bulk-assignment/{endpoint}", json=payload)
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(overrides)


def test_preview_endpoint_encodes_context_and_submit(setup_bulk):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.accounts import router
    from core.auth import get_current_active_user
    app = FastAPI()
    app.include_router(router)
    from core.database import get_db
    db, owner, *_ = setup_bulk
    overrides = dict(app.dependency_overrides)
    try:
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_active_user] = lambda: owner
        client = TestClient(app)
        headers = {}
        payload = request_for(setup_bulk).model_dump()
        context = client.post("/api/v1/accounts/bulk-assignment/context", json={"account_ids": payload["account_ids"]}, headers=headers)
        assert context.status_code == 200 and len(context.json()["items"]) == 2
        response = client.post("/api/v1/accounts/bulk-assignment/preview", json=payload, headers=headers)
        assert response.status_code == 200 and response.json()["ready_count"] == 2
        payload.update(idempotency_key=str(uuid.uuid4()), preview_hashes={x["account_id"]: x["preview_hash"] for x in response.json()["items"]})
        response = client.post("/api/v1/accounts/bulk-assignment/submit", json=payload, headers=headers)
        assert response.status_code == 200 and response.json()["success_count"] == 2
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(overrides)
