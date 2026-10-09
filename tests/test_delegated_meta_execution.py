"""Explicit delegated execution stays scoped to an assigned account and actor."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from api import accounts, meta_connections, meta_pages
from models import (User, UserAccount, AdAccount, MetaConnection, MetaConnectionAsset,
                    MetaPage, CampaignJob, CampaignJobItem, AuditLog)
from services.credential_resolver import CredentialResolver
from services.meta.page_access import page_account_access_error
from services.meta_execution_access import execution_candidates


@pytest.fixture
def delegated_setup(db, monkeypatch):
    users = [User(id=f"delegate-{role}", username=role, email=f"{role}@delegated.local", role=role,
        hashed_password="unused", is_active=True, permissions=["job:create"], settings={})
        for role in ("owner", "user", "tenant_admin")]
    owner, publisher, admin = users
    owner.role = "user"
    connection = MetaConnection(id="delegate-connection", meta_user_id="fb-owner", app_id="delegated-app",
        access_mode="connector", credential_id="opaque-owner", authorized_by_user_id=owner.id,
        status="ACTIVE", scopes=["ads_read", "ads_management"], expires_at=datetime.utcnow() + timedelta(days=30))
    account = AdAccount(id="delegate-account", account_id="act_delegate", account_name="Delegated account",
        connection_id=connection.id, connector_credential_id=connection.credential_id,
        system_status="ACTIVE", account_status="1")
    page = MetaPage(id="delegate-page", page_id="101", page_name="Authorized Page", credential_id=connection.credential_id,
        connector_credential_id=connection.credential_id, connection_id=connection.id, status="ACTIVE", tasks=["ADVERTISE"])
    db.add_all([*users, connection, account, page])
    db.flush()
    db.add_all([
        MetaConnectionAsset(id="delegate-account-grant", connection_id=connection.id, asset_type="AD_ACCOUNT", asset_id=account.id, status="ACTIVE"),
        MetaConnectionAsset(id="delegate-page-grant", connection_id=connection.id, asset_type="PAGE", asset_id=page.id, status="ACTIVE", tasks=["ADVERTISE"]),
        UserAccount(id="delegate-primary", account_id=account.id, user_id=owner.id, role="owner", assignment_status="ACTIVE", assignment_role="PRIMARY"),
        UserAccount(id="delegate-assignment", account_id=account.id, user_id=publisher.id, role="publisher", assignment_status="ACTIVE"),
    ])
    db.flush()
    monkeypatch.setattr(db, "commit", db.flush)
    monkeypatch.setattr(accounts, "_require_account_operation_lease", lambda *args: None)
    return owner, publisher, admin, connection, account, page


def delegate(db, setup, **fields):
    owner, publisher, admin, connection, account, _ = setup
    return accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id],
        execution_connection_id=connection.id, **fields), admin, db)


def test_account_assignment_alone_does_not_grant_execution(db, delegated_setup):
    _, publisher, _, connection, account, _ = delegated_setup
    with pytest.raises(ValueError, match="委派授权"):
        CredentialResolver(db).for_account(account.id, actor_id=publisher.id)
    with pytest.raises(ValueError):
        CredentialResolver(db).for_account(account.id, actor_id=publisher.id, connection_id=connection.id)
    assert meta_pages.list_pages("ACTIVE", db, publisher) == []
    assert meta_connections.list_connections("mine", db, publisher) == []


def test_admin_without_personal_oauth_uses_explicit_account_delegation(db, delegated_setup):
    owner, _, admin, connection, account, _ = delegated_setup
    with pytest.raises(ValueError, match="委派授权"):
        CredentialResolver(db).for_account(account.id, actor_id=admin.id)
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[admin.id],
        execution_connection_id=connection.id), admin, db)
    ref = CredentialResolver(db).for_account(account.id, actor_id=admin.id)
    assert ref.connection_id == connection.id and ref.token is None
    db.info["meta_actor_id"] = admin.id
    result = accounts.account_to_dict(account, db)
    assert result["execution_source"] == "DELEGATED"
    assert result["authorized_by_user_id"] == owner.id
    assert result["authorization_connection_id"] == connection.id
    assert meta_connections.list_connections("mine", db, admin) == []
    assert connection.authorized_by_user_id == owner.id


def test_admin_clearing_delegation_does_not_implicitly_use_other_users_oauth(db, delegated_setup):
    _, _, admin, connection, account, _ = delegated_setup
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[admin.id],
        execution_connection_id=connection.id), admin, db)
    assert CredentialResolver(db).for_account(account.id, actor_id=admin.id).connection_id == connection.id
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[admin.id],
        execution_connection_id=None), admin, db)
    with pytest.raises(ValueError, match="委派授权"):
        CredentialResolver(db).for_account(account.id, actor_id=admin.id)


def test_admin_delegates_without_transferring_owner_or_canonical_identity(db, delegated_setup):
    owner, publisher, admin, connection, account, page = delegated_setup
    delegate(db, delegated_setup)
    ref = CredentialResolver(db).for_account(account.id, actor_id=publisher.id)
    assert ref.connection_id == connection.id and ref.credential_id == "opaque-owner" and ref.token is None
    assert connection.authorized_by_user_id == owner.id
    assert account.connection_id == connection.id
    assert db.query(UserAccount).filter_by(account_id=account.id, assignment_role="PRIMARY").one().user_id == owner.id
    row = db.query(UserAccount).filter_by(user_id=publisher.id, account_id=account.id).one()
    assert row.execution_granted_by == admin.id and row.execution_granted_at
    db.info["meta_actor_id"] = publisher.id
    assert page_account_access_error(page, account) is None
    assert [x["page_id"] for x in meta_pages.list_pages("ACTIVE", db, publisher)] == ["101"]
    assert [x["page_id"] for x in meta_pages.list_pages("ACTIVE", db, publisher, [account.id])] == ["101"]
    result = accounts.account_to_dict(account, db)
    assert result["execution_source"] == "DELEGATED" and result["authorized_by_user_id"] == owner.id
    log = db.query(AuditLog).filter_by(action="ASSIGN_ACCOUNT_EXECUTION").one()
    assert log.user_id == admin.id and log.request_data["execution_connection_id"] == connection.id


def test_delegated_summary_exposes_only_assigned_accounts_and_no_management(db, delegated_setup):
    _, publisher, _, connection, account, _ = delegated_setup
    delegate(db, delegated_setup)
    second = AdAccount(id="delegate-hidden", account_id="act_hidden", account_name="Hidden account")
    db.add(second)
    db.flush()
    db.add(MetaConnectionAsset(id="delegate-hidden-grant", connection_id=connection.id, asset_type="AD_ACCOUNT", asset_id=second.id, status="ACTIVE"))
    db.flush()
    result = meta_connections.list_connections("delegated", db, publisher)
    assert len(result) == 1 and result[0]["account_names"] == [account.account_name]
    assert result[0]["account_count"] == 1 and result[0]["can_manage"] is False
    assert "credential_id" not in result[0] and result[0]["execution_source"] == "DELEGATED"
    with pytest.raises(ValueError):
        CredentialResolver(db).for_account(second.id, actor_id=publisher.id, connection_id=connection.id)
    for func in (meta_connections.sync_connection, meta_connections.disconnect):
        with pytest.raises(HTTPException) as error:
            func(connection.id, db, publisher)
        assert error.value.status_code == 403


@pytest.mark.parametrize("invalid", ["assignment_revoked", "assignment_expired", "readonly", "owner_disabled", "connection_revoked", "connection_expired", "account_grant_revoked"])
def test_revocation_and_expiry_block_execution_and_queued_snapshots(db, delegated_setup, invalid):
    owner, publisher, _, connection, account, _ = delegated_setup
    delegate(db, delegated_setup)
    job = CampaignJob(id="delegate-job", created_by=publisher.id, action_type="CREATE")
    item = CampaignJobItem(id="delegate-item", job=job, ad_account_id=account.id,
        authorization_connection_id=connection.id, authorization_version=connection.version)
    db.add(item)
    db.flush()
    assert CredentialResolver(db).for_job_item(item).connection_id == connection.id
    assignment = db.query(UserAccount).filter_by(user_id=publisher.id, account_id=account.id).one()
    if invalid == "assignment_revoked": assignment.assignment_status = "REVOKED"
    if invalid == "assignment_expired": assignment.expires_at = datetime.utcnow() - timedelta(seconds=1)
    if invalid == "readonly": assignment.role = "viewer"
    if invalid == "owner_disabled": owner.is_active = False
    if invalid == "connection_revoked": connection.status = "REVOKED"
    if invalid == "connection_expired": connection.expires_at = datetime.utcnow() - timedelta(seconds=1)
    if invalid == "account_grant_revoked": db.query(MetaConnectionAsset).filter_by(id="delegate-account-grant").one().status = "REVOKED"
    db.flush()
    with pytest.raises(ValueError): CredentialResolver(db).for_job_item(item)
    from tasks.campaign_tasks import _validate_item_actor
    with pytest.raises((ValueError, HTTPException)):
        _validate_item_actor(db, item)
    assert meta_pages.list_pages("ACTIVE", db, publisher) == []


def test_personal_reset_and_missing_field_have_distinct_meanings(db, delegated_setup):
    _, publisher, admin, connection, account, _ = delegated_setup
    delegate(db, delegated_setup)
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id]), admin, db)
    assert CredentialResolver(db).for_account(account.id, actor_id=publisher.id).connection_id == connection.id
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id], execution_connection_id=None), admin, db)
    with pytest.raises(ValueError): CredentialResolver(db).for_account(account.id, actor_id=publisher.id)
    row = db.query(UserAccount).filter_by(user_id=publisher.id, account_id=account.id).one()
    assert row.execution_connection_id is None and row.execution_granted_by is None


def test_unassign_and_reassign_does_not_restore_delegated_execution(db, delegated_setup):
    _, publisher, admin, _, account, _ = delegated_setup
    delegate(db, delegated_setup)
    accounts.unassign_user(account.id, accounts.AssignUsers(user_ids=[publisher.id]), admin, db)
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id]), admin, db)
    with pytest.raises(ValueError): CredentialResolver(db).for_account(account.id, actor_id=publisher.id)


def test_multiple_accounts_require_common_page_and_access_is_checked(db, delegated_setup):
    owner, publisher, admin, _, account, page = delegated_setup
    delegate(db, delegated_setup)
    connection = MetaConnection(id="delegate-other-connection", meta_user_id="fb-other", app_id="delegated-app",
        access_mode="connector", credential_id="opaque-other", authorized_by_user_id=owner.id,
        status="ACTIVE", scopes=["ads_read", "ads_management"])
    second = AdAccount(id="delegate-second", account_id="act_second")
    db.add_all([connection, second])
    db.flush()
    db.add(MetaConnectionAsset(id="delegate-second-grant", connection_id=connection.id, asset_type="AD_ACCOUNT", asset_id=second.id, status="ACTIVE"))
    db.flush()
    with pytest.raises(HTTPException): meta_pages.list_pages("ACTIVE", db, publisher, [second.id])
    accounts.assign_users(second.id, accounts.AssignUsers(user_ids=[publisher.id], execution_connection_id=connection.id), admin, db)
    assert meta_pages.list_pages("ACTIVE", db, publisher, [account.id, second.id]) == []
    db.add(MetaConnectionAsset(id="delegate-second-page-grant", connection_id=connection.id, asset_type="PAGE", asset_id=page.id, status="ACTIVE", tasks=["ADVERTISE"]))
    db.flush()
    assert [x["page_id"] for x in meta_pages.list_pages("ACTIVE", db, publisher, [account.id, second.id])] == [page.page_id]


def test_admin_cannot_delegate_missing_or_expired_connection(db, delegated_setup):
    _, publisher, admin, connection, account, _ = delegated_setup
    assert len(execution_candidates(db, account)) == 1
    connection.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.flush()
    assert execution_candidates(db, account) == []
    for connection_id in (connection.id, "unrelated-connection"):
        with pytest.raises(HTTPException) as error:
            accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id], execution_connection_id=connection_id), admin, db)
        assert error.value.status_code == 400


def test_expired_assignment_cannot_restore_delegation_with_keep(db, delegated_setup):
    _, publisher, admin, _, account, _ = delegated_setup
    delegate(db, delegated_setup)
    row = db.query(UserAccount).filter_by(user_id=publisher.id, account_id=account.id).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.flush()
    accounts.assign_users(account.id, accounts.AssignUsers(user_ids=[publisher.id]), admin, db)
    assert row.assignment_status == "ACTIVE" and row.execution_connection_id is None
    with pytest.raises(ValueError):
        CredentialResolver(db).for_account(account.id, actor_id=publisher.id)


def test_cross_tenant_execution_is_blocked_even_with_explicit_connection(db, delegated_setup):
    from core.tenant import bypass_tenant
    _, _, _, connection, account, _ = delegated_setup
    publisher = User(id="other-tenant-user", username="Other tenant", email="other@delegated.local",
        hashed_password="unused", tenant_id="other-tenant", role="user", is_active=True)
    db.add(publisher)
    db.flush()
    with bypass_tenant(), pytest.raises(ValueError):
        CredentialResolver(db).for_account(account.id, actor_id=publisher.id, connection_id=connection.id)


def test_delegation_migration_preserves_existing_assignment_without_grant():
    import importlib
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = importlib.import_module("migrations.versions.0075_delegated_meta_execution")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE user_accounts (id VARCHAR(50) PRIMARY KEY, user_id VARCHAR(50))")
        conn.exec_driver_sql("INSERT INTO user_accounts VALUES ('existing', 'publisher')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            row = conn.exec_driver_sql("SELECT * FROM user_accounts").mappings().one()
            assert row["user_id"] == "publisher" and row["execution_connection_id"] is None
            assert row["execution_granted_by"] is None and row["execution_granted_at"] is None
            assert "ix_user_accounts_execution_connection_id" in {x["name"] for x in sa.inspect(conn).get_indexes("user_accounts")}
            migration.downgrade()
        assert [x["name"] for x in sa.inspect(conn).get_columns("user_accounts")] == ["id", "user_id"]
        assert conn.exec_driver_sql("SELECT user_id FROM user_accounts").scalar_one() == "publisher"
    engine.dispose()
