"""Ownership and immutable execution identity regressions; no real Meta calls."""
import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
import jwt
import pytest
from sqlalchemy.orm import Session
from fastapi import HTTPException

from api import meta_auth, meta_connections
from config.settings import settings
from core.enums import ActionType
from core.tenant import tenant_scope
from models import (User, Tenant, AdAccount, UserAccount, MetaConnection, MetaConnectionAsset,
                    MetaOAuthSession, MetaPage, CampaignTemplate, CampaignJob, CampaignJobItem, SyncAlert)
from services.credential_resolver import CredentialResolver
from services.meta_connection_service import (bind_connection, grant_asset, connection_health,
    suspend_user_authorizations, inspect_personal_authorizations)
from services.meta_connection_sync import import_connection_accounts
from services.meta.page_access import page_account_access_error


@pytest.fixture
def publishers(db):
    users = [User(id=f"personal-{role}", username=f"personal-{role}", email=f"{role}@personal.local",
                  hashed_password="unused", role="tenant_admin" if role == "admin" else "user",
                  tenant_id="test_tenant", is_active=True, settings={}, permissions=["job:create"]) for role in ("a", "b", "admin")]
    db.add_all(users)
    db.flush()
    return users


@pytest.fixture
def auth_db(db):
    # Each simulated HTTP commit/rollback remains inside the test's outer transaction.
    session = Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")
    yield session
    session.close()


def connect(db, user, identity="meta-a", credential="opaque-a", expires=None):
    return bind_connection(db, user, {"meta_user_id": identity, "app_id": "test-meta-app", "credential_id": credential,
        "scopes": ["ads_management", "ads_read"], "expires_at": expires or datetime.utcnow() + timedelta(days=30)}, mode="connector")


def shared_account(db, publishers):
    a, b, _ = publishers
    one, two = connect(db, a), connect(db, b, "meta-b", "opaque-b")
    account = AdAccount(id="personal-account", account_id="act_101", account_name="Shared account",
                        connection_id=one.id, connector_credential_id="opaque-a", account_status="1", system_status="ACTIVE")
    db.add(account)
    db.flush()
    for user, conn in ((a, one), (b, two)):
        grant_asset(db, conn, "AD_ACCOUNT", account.id)
        db.add(UserAccount(id=f"assign-{user.id}", user_id=user.id, account_id=account.id, role="editor", assignment_status="ACTIVE"))
    db.flush()
    return account, one, two


def test_opaque_credential_is_not_authorization(db, publishers, monkeypatch):
    a, b, _ = publishers
    row = connect(db, a)
    remote = Mock()
    monkeypatch.setattr(meta_auth, "FBConnectorClient", lambda: remote)
    with pytest.raises(HTTPException) as error:
        meta_auth.oauth_ad_accounts(row.credential_id, db, b)
    assert error.value.status_code == 403
    remote.oauth_ad_accounts.assert_not_called()
    with pytest.raises(HTTPException):
        meta_auth.oauth_complete_accounts(meta_auth.OAuthAccountsCompleteRequest(credential_id=row.credential_id, account_ids=["act_101"]), db, b)
    remote.oauth_ad_accounts.assert_not_called()


def test_ordinary_members_have_self_entry_and_tenant_list_is_admin_only(db, publishers):
    a, b, admin = publishers
    connect(db, a)
    connect(db, b, "meta-b", "opaque-b")
    assert len(meta_connections.list_connections("mine", db, a)) == 1
    with pytest.raises(HTTPException) as error:
        meta_connections.list_connections("tenant", db, a)
    assert error.value.status_code == 403
    assert len(meta_connections.list_connections("tenant", db, admin)) == 2
    assert asyncio.run(__import__("core.auth", fromlist=["require_meta_self"]).require_meta_self(a)) is a


def test_same_meta_identity_cannot_transfer_ownership(db, publishers):
    a, b, _ = publishers
    row = connect(db, a)
    with pytest.raises(HTTPException) as error:
        connect(db, b)
    assert error.value.status_code == 409
    assert row.authorized_by_user_id == a.id
    assert row.credential_id == "opaque-a"
    other = connect(db, a, "meta-other", "opaque-other")
    with pytest.raises(HTTPException):
        bind_connection(db, a, {"meta_user_id": other.meta_user_id, "app_id": other.app_id}, mode="connector", expected_connection_id=row.id)


def test_new_import_assigns_owner_existing_import_preserves_policy(db, publishers):
    a, b, _ = publishers
    one = connect(db, a)
    imported = import_connection_accounts(db, one, a, [{"id": "act_101", "name": "Campaign account", "account_status": 1, "business": {"id": "bm101", "name": "Shared BM"}}])
    account = db.query(AdAccount).filter_by(id=imported[0]["id"]).one()
    primary = db.query(UserAccount).filter_by(account_id=account.id, assignment_role="PRIMARY").one()
    assert primary.user_id == a.id and primary.assignment_type == "OAUTH"
    account.system_status = "DISABLED"
    account.system_status_reason = "admin freeze"
    two = connect(db, b, "meta-b", "opaque-b")
    result = import_connection_accounts(db, two, b, [{"id": "act_101", "name": "Same account", "account_status": 1, "business": {"id": "bm101"}}])
    assert result[0]["assignment_required"] is True
    assert account.connection_id == one.id
    assert account.connector_credential_id == "opaque-a"
    assert account.business.connector_credential_id == "opaque-a"
    assert account.system_status == "DISABLED" and account.system_status_reason == "admin freeze"
    assert db.query(MetaConnectionAsset).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).count() == 2
    assert db.query(UserAccount).filter_by(account_id=account.id, assignment_role="PRIMARY").one().user_id == a.id


def test_execution_uses_actor_and_snapshot_not_latest_token(db, publishers):
    account, one, two = shared_account(db, publishers)
    a, b, _ = publishers
    resolver = CredentialResolver(db)
    assert resolver.for_account(account.id, actor_id=a.id).credential_id == "opaque-a"
    assert resolver.for_account(account.id, actor_id=b.id).credential_id == "opaque-b"
    job = CampaignJob(id="personal-job", created_by=a.id)
    item = CampaignJobItem(id="personal-item", job=job, ad_account_id=account.id,
                          authorization_connection_id=one.id, authorization_version=one.version)
    db.add(item)
    db.flush()
    connect(db, a, credential="opaque-a-refreshed")
    ref = resolver.for_job_item(item)
    assert ref.connection_id == one.id and ref.credential_id == "opaque-a-refreshed"
    assert ref.version > item.authorization_version
    one.status = "REVOKED"
    with pytest.raises(ValueError):
        resolver.for_job_item(item)
    assert resolver.for_account(account.id, actor_id=b.id, connection_id=two.id).credential_id == "opaque-b"


def test_multiple_own_identities_require_explicit_choice(db, publishers):
    account, one, _ = shared_account(db, publishers)
    a = publishers[0]
    extra = connect(db, a, "meta-extra", "opaque-extra")
    grant_asset(db, extra, "AD_ACCOUNT", account.id)
    db.flush()
    with pytest.raises(ValueError, match="多个个人授权"):
        CredentialResolver(db).for_account(account.id, actor_id=a.id)
    meta_connections.choose_execution_identity(extra.id, meta_connections.ExecutionDefaultRequest(account_ids=[account.id]), db, a)
    assert CredentialResolver(db).for_account(account.id, actor_id=a.id).connection_id == extra.id
    assert CredentialResolver(db).for_account(account.id, actor_id=a.id, connection_id=one.id).connection_id == one.id


def test_page_grants_are_independent_and_revoke_one_does_not_break_other(db, publishers, monkeypatch):
    from services.meta.connector_page_sync import sync_connector_pages
    account, one, two = shared_account(db, publishers)
    remote = SimpleNamespace(sync_pages=lambda credential: {"pages": [{"id": "page101", "name": "Shared Page", "tasks": ["ADVERTISE"]}]})
    monkeypatch.setattr("services.meta.connector_page_sync.FBConnectorClient", lambda: remote)
    sync_connector_pages(db, "test_tenant", one.credential_id)
    db.flush()
    sync_connector_pages(db, "test_tenant", two.credential_id)
    db.flush()
    page = db.query(MetaPage).filter_by(page_id="page101").one()
    assert page.connection_id == one.id
    db.info["meta_actor_id"] = publishers[1].id
    assert page_account_access_error(page, account) is None
    remote.sync_pages = lambda credential: {"pages": []}
    sync_connector_pages(db, "test_tenant", one.credential_id)
    db.flush()
    assert page.status == "ACTIVE"
    assert page_account_access_error(page, account) is None
    db.info["meta_actor_id"] = publishers[0].id
    assert "Page" in page_account_access_error(page, account)


def test_signed_callback_claim_requires_matching_user_state_and_single_use(auth_db, publishers, monkeypatch):
    db = auth_db
    a, b, _ = publishers
    monkeypatch.setattr(settings, "FB_ACCESS_MODE", "connector")
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "test-oauth-receipt-signing-key-32-characters")
    state = meta_auth._new_oauth_state(a, "test_tenant", db=db)
    signed = jwt.encode({"aud": "saas-meta-oauth", "exp": datetime.utcnow() + timedelta(minutes=10),
        "state_hash": sha256(state.encode()).hexdigest(), "credential_id": "opaque-returned"}, settings.FB_CONNECTOR_SIGNING_KEY, algorithm="HS256")
    request = meta_auth.OAuthClaimRequest(state=state, receipt=signed)
    remote = SimpleNamespace(credential_health=Mock(return_value={"items": [{"id": "opaque-returned", "app_id": "test-meta-app",
        "meta_user_id": "meta-a", "status": "ACTIVE", "scopes": ["ads_read", "ads_management"]}]}))
    monkeypatch.setattr(meta_auth, "FBConnectorClient", lambda: remote)
    with pytest.raises(HTTPException) as error:
        meta_auth.claim_oauth(request, db, b)
    assert error.value.status_code == 403
    remote.credential_health.assert_not_called()
    result = meta_auth.claim_oauth(request, db, a)
    assert result["credential_id"] == "opaque-returned"
    assert db.query(MetaConnection).filter_by(id=result["connection_id"]).one().authorized_by_user_id == a.id
    with pytest.raises(HTTPException, match="") as error:
        meta_auth.claim_oauth(request, db, a)
    assert error.value.status_code == 400
    assert remote.credential_health.call_count == 1
    other_state = meta_auth._new_oauth_state(a, "test_tenant", db=db)
    with pytest.raises(HTTPException):
        meta_auth.claim_oauth(meta_auth.OAuthClaimRequest(state=other_state, receipt=signed), db, a)


def test_expired_state_and_cross_tenant_credential_rejected(db, publishers):
    a = publishers[0]
    state = meta_auth._new_oauth_state(a, "test_tenant", db=db)
    intent = db.query(MetaOAuthSession).one()
    intent.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.flush()
    with pytest.raises(HTTPException):
        meta_auth._consume_state(db, state, a)
    db.add(Tenant(id="personal-other-tenant", name="Other", slug="personal-other"))
    db.flush()
    with tenant_scope("personal-other-tenant"):
        db.add(MetaConnection(id="foreign-personal", tenant_id="personal-other-tenant", meta_user_id="other", app_id="app", credential_id="foreign-opaque", authorized_by_user_id=a.id))
        db.flush()
    with pytest.raises(HTTPException) as error:
        meta_auth.oauth_ad_accounts("foreign-opaque", db, a)
    assert error.value.status_code == 404


def test_job_submission_pins_identity_and_offboarding_preserves_history(db, publishers, monkeypatch):
    from services.job_service import JobService
    import services.job_service as jobs
    account, one, two = shared_account(db, publishers)
    a, b, _ = publishers
    db.info["meta_actor_id"] = a.id
    template = CampaignTemplate(id="personal-template", name="Personal deployment", creative_config_json={})
    db.add(template)
    db.flush()
    monkeypatch.setattr(jobs, "execute_campaign_job", SimpleNamespace(delay=Mock(return_value=SimpleNamespace(id="queued-personal-task"))))
    job = JobService(db).create_job(template_id=template.id, ad_account_ids=[account.id], action_type=ActionType.PAUSE, created_by=a.id)
    assert job.items[0].authorization_connection_id == one.id
    assert job.items[0].authorization_version == one.version
    completed = CampaignJob(id="personal-completed", created_by=a.id, status="SUCCESS")
    db.add(completed)
    db.flush()
    suspend_user_authorizations(db, a.id)
    db.flush()
    assert job.status == "CANCELLED" and job.items[0].status == "SKIPPED"
    assert completed.status == "SUCCESS"
    assert one.status == "SUSPENDED" and two.status == "ACTIVE"
    from tasks.campaign_tasks import _validate_item_actor, _finalize_job_if_done
    assert _validate_item_actor(db, job.items[0]) is True
    _finalize_job_if_done(db, job.id)
    assert job.status == "CANCELLED"
    assert db.query(AdAccount).filter_by(id=account.id).count() == 1
    assert db.query(UserAccount).filter_by(user_id=b.id, assignment_status="ACTIVE").count() == 1


@pytest.mark.parametrize("days,expected", [(30, "ACTIVE"), (5, "EXPIRING"), (0.5, "EXPIRING_1_DAY"), (-1, "EXPIRED")])
def test_data_access_deadline_is_checked_even_with_long_token_expiry(db, publishers, days, expected):
    row = connect(db, publishers[0])
    row.data_access_expires_at = datetime.utcnow() + timedelta(days=days)
    assert connection_health(row) == expected


def test_overseas_callback_signs_result_for_exact_state(monkeypatch):
    from fb_connector.api import oauth
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "test-oauth-receipt-signing-key-32-characters")
    async def exchange(payload):
        return {"credential_id": "opaque-new", "meta_user_id": "meta-a", "data_access_expires_at": datetime.utcnow() + timedelta(days=60)}
    monkeypatch.setattr(oauth, "exchange", exchange)
    state = jwt.encode({"return_to": "http://49.232.238.163:8094"}, "test-local-state-key-with-enough-characters", algorithm="HS256")
    response = asyncio.run(oauth.callback(state=state, code="unused", error=None, error_description=None))
    query = parse_qs(urlparse(response.headers["location"]).query)
    receipt = jwt.decode(query["receipt"][0], settings.FB_CONNECTOR_SIGNING_KEY, algorithms=["HS256"], audience="saas-meta-oauth")
    assert receipt["credential_id"] == "opaque-new"
    assert receipt["state_hash"] == sha256(state.encode()).hexdigest()
    assert "access_token" not in query


def test_health_alerts_are_deduplicated_and_resolved_after_reauthorization(db, publishers, monkeypatch):
    row = connect(db, publishers[0])
    row.data_access_expires_at = datetime.utcnow() + timedelta(hours=12)
    remote = SimpleNamespace(credential_health=lambda ids: {"items": [{"id": row.credential_id, "status": "ACTIVE", "scopes": row.scopes, "expires_at": row.expires_at.isoformat()}]})
    monkeypatch.setattr("services.fb_connector_client.FBConnectorClient", lambda: remote)
    assert inspect_personal_authorizations(db) == 1
    assert inspect_personal_authorizations(db) == 1
    assert db.query(SyncAlert).filter_by(is_resolved=False).count() == 1
    row.data_access_expires_at = datetime.utcnow() + timedelta(days=60)
    assert inspect_personal_authorizations(db) == 0
    assert db.query(SyncAlert).filter_by(is_resolved=False).count() == 0


def test_reporting_identity_handoff_requires_explicit_admin_choice(db, publishers):
    account, one, two = shared_account(db, publishers)
    a, b, admin = publishers
    payload = meta_connections.ExecutionDefaultRequest(account_ids=[account.id])
    with pytest.raises(HTTPException) as error:
        meta_connections.choose_reporting_identity(two.id, payload, db, b)
    assert error.value.status_code == 403
    assert CredentialResolver(db).for_account(account.id).connection_id == one.id
    meta_connections.choose_reporting_identity(two.id, payload, db, admin)
    assert CredentialResolver(db).for_account(account.id).connection_id == two.id
    one.status = "SUSPENDED"
    assert CredentialResolver(db).for_account(account.id).credential_id == "opaque-b"
    legacy_job = CampaignJob(id="old-unpinned-job", created_by=a.id)
    item = CampaignJobItem(id="old-unpinned-item", job=legacy_job, ad_account_id=account.id)
    db.add(item)
    db.flush()
    with pytest.raises(ValueError, match="没有个人授权快照"):
        CredentialResolver(db).for_job_item(item)


def test_direct_oauth_storage_is_atomic_and_never_changes_another_person(db, publishers, monkeypatch):
    from models import Credential
    a, b, _ = publishers
    monkeypatch.setattr(settings, "FB_APP_ID", "test-meta-app")
    commit = Mock()
    monkeypatch.setattr(db, "commit", commit)
    token = {"access_token": "synthetic-long-user-token", "meta_user_id": "meta-a", "expires_at": datetime.utcnow() + timedelta(days=30)}
    row = meta_auth._store_direct(db, a, token, ["ads_read", "ads_management"])
    cred = db.query(Credential).filter_by(id=row.credential_id).one()
    assert cred.granted_by_user_id == a.id and cred.get_access_token() == token["access_token"]
    assert cred.access_token_encrypted != token["access_token"]
    with pytest.raises(HTTPException):
        meta_auth._store_direct(db, b, token, ["ads_read", "ads_management"])
    assert cred.granted_by_user_id == a.id and db.query(Credential).count() == 1
    commit.assert_not_called()


def test_credential_failure_affects_only_the_executing_publisher(db, publishers):
    from services.credential_service import CredentialService
    account, one, two = shared_account(db, publishers)
    db.info["meta_actor_id"] = publishers[0].id
    db.info["meta_connection_id"] = one.id
    CredentialService(db).mark_invalid_by_account(account.id, "synthetic revoked token")
    assert one.status == "INVALID" and one.last_error == "synthetic revoked token"
    assert two.status == "ACTIVE" and two.last_error is None
    assert CredentialResolver(db).for_account(account.id, actor_id=publishers[1].id, connection_id=two.id).credential_id == "opaque-b"


def test_pending_media_identity_is_immutable_until_explicit_failed_retry(db, publishers):
    from models import CreativeAsset
    from services.media_binding_service import ensure_asset_bindings
    account, one, two = shared_account(db, publishers)
    asset = CreativeAsset(id="personal-media", name="Test image", asset_type="image", status="READY")
    db.add(asset)
    db.flush()
    db.info["meta_actor_id"] = publishers[0].id
    binding = ensure_asset_bindings(db, [asset.id], [account.id])[0]
    assert binding.authorization_connection_id == one.id and binding.requested_by == publishers[0].id
    db.info["meta_actor_id"] = publishers[1].id
    assert ensure_asset_bindings(db, [asset.id], [account.id])[0] is binding
    assert binding.authorization_connection_id == one.id and binding.requested_by == publishers[0].id
    binding.status = "FAILED"
    ensure_asset_bindings(db, [asset.id], [account.id], reset_failed=False)
    assert binding.authorization_connection_id == one.id
    ensure_asset_bindings(db, [asset.id], [account.id], reset_failed=True)
    assert binding.authorization_connection_id == two.id and binding.requested_by == publishers[1].id
    resolver = CredentialResolver(db)
    with pytest.raises(ValueError, match="没有个人授权快照"):
        resolver.validate_snapshot(account.id, None)
    resolver.validate_snapshot(account.id, binding.authorization_connection_id)


@pytest.mark.parametrize("asset_type", ["BUSINESS", "AD_ACCOUNT", "PAGE"])
def test_pending_grants_are_reused_with_production_autoflush_disabled(db, publishers, asset_type):
    db.autoflush = False
    connection = connect(db, publishers[0])
    first = grant_asset(db, connection, asset_type, "shared-asset", ["ADVERTISE"])
    second = grant_asset(db, connection, asset_type, "shared-asset", ["MANAGE"])
    assert second is first
    assert second.tasks == ["MANAGE"]
    db.flush()
    assert db.query(MetaConnectionAsset).filter_by(connection_id=connection.id,
        asset_type=asset_type, asset_id="shared-asset").count() == 1
    second.status = "REVOKED"
    assert grant_asset(db, connection, asset_type, "shared-asset") is first
    db.flush()
    assert first.status == "ACTIVE"


def test_complete_multiple_existing_accounts_in_same_bm_and_retry(auth_db, publishers, monkeypatch):
    from models import MetaAccount
    from services import meta_connection_sync
    from tasks.meta_sync_tasks import sync_personal_connection_task
    db = auth_db
    db.autoflush = False
    publisher, original_owner, _ = publishers
    original_connection = connect(db, original_owner, "original-meta", "original-credential")
    connection = connect(db, publisher)
    for business in ("bm-a", "bm-b"):
        db.add(MetaAccount(id=business, business_id=business, name=business,
            connection_id=original_connection.id, connector_credential_id="original-credential"))
    db.flush()
    remote = []
    for number, business in enumerate(("bm-a", "bm-b", "bm-a")):
        account = AdAccount(id=f"batch-local-{number}", account_id=f"act_batch_{number}",
            business_id=business, account_name=f"Account {number}",
            connection_id=original_connection.id, connector_credential_id="original-credential",
            system_status="DISABLED", system_status_reason="original restriction")
        db.add(account)
        db.flush()
        db.add(UserAccount(id=f"batch-owner-{number}", user_id=original_owner.id,
            account_id=account.id, role="owner", assignment_role="PRIMARY", assignment_status="ACTIVE"))
        remote.append({"id": account.account_id, "name": account.account_name,
            "business": {"id": business, "name": business}})
    db.flush()
    client = SimpleNamespace(oauth_ad_accounts=lambda credential: {"accounts": remote})
    monkeypatch.setattr(meta_auth, "FBConnectorClient", lambda: client)
    pages = Mock(return_value={"count": 0})
    queue = Mock()
    monkeypatch.setattr(meta_connection_sync, "sync_connection_pages", pages)
    monkeypatch.setattr(sync_personal_connection_task, "delay", queue)
    payload = meta_auth.OAuthAccountsCompleteRequest(credential_id=connection.credential_id,
        account_ids=[row["id"] for row in remote])
    for _ in range(2):
        result = meta_auth.oauth_complete_accounts(payload, db, publisher)
        assert result["success"] is True and len(result["accounts"]) == 3
        assert all(row["assignment_required"] for row in result["accounts"])
        assert db.query(MetaConnectionAsset).filter_by(connection_id=connection.id,
            asset_type="BUSINESS").count() == 2
        assert db.query(MetaConnectionAsset).filter_by(connection_id=connection.id,
            asset_type="AD_ACCOUNT").count() == 3
    assert queue.call_count == 2
    assert db.query(UserAccount).filter_by(user_id=publisher.id).count() == 0
    for account in db.query(AdAccount).filter(AdAccount.id.like("batch-local-%")).all():
        assert account.connection_id == original_connection.id
        assert account.connector_credential_id == "original-credential"
        assert account.system_status == "DISABLED"
        assert account.system_status_reason == "original restriction"
        assert db.query(UserAccount).filter_by(account_id=account.id, assignment_role="PRIMARY").one().user_id == original_owner.id
