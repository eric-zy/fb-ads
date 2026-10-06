import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

from api.meta_instagram import instagram_sync_status, list_instagram_identities, sync_instagram_identities
from core.tenant import tenant_scope
from models import AdAccount, AsyncTaskRecord, CampaignJob, CampaignJobItem, CampaignTemplate, MetaPage, User
from models.meta_instagram import MetaInstagramSnapshot
from services.connector_campaign_builder import build_connector_payload
from services.instagram_identity import instagram_account_access_error, instagram_references
from services.job_service import JobService
from services.meta import MetaClient
from services.meta_instagram_service import MetaInstagramSyncService


def seed(db):
    account = AdAccount(id="ig-account", account_id="act_123", connector_credential_id="ig-credential")
    page = MetaPage(id="ig-page", page_id="100", page_name="IG Page", credential_id="ig-credential",
                    connector_credential_id="ig-credential", tasks=["ADVERTISE"], status="ACTIVE")
    snapshot = MetaInstagramSnapshot(id="ig-snapshot", ad_account_id=account.id, credential_id="ig-credential",
        status="HEALTHY", items=[{"id": "200", "username": "brand", "page_ids": ["100"]}], last_synced_at=datetime.utcnow())
    template = CampaignTemplate(id="ig-template", name="IG template", status="ACTIVE", objective="OUTCOME_TRAFFIC",
        daily_budget=10, budget_type="DAILY", optimization_goal="LINK_CLICKS", billing_event="IMPRESSIONS",
        targeting_json={"geo_locations": {"countries": ["US"]}}, placement_json={},
        creative_config_json={"page_id": "100", "instagram_user_id": "200",
                              "creatives": [{"image_hash": "image-1", "landing_url": "https://example.com"}]})
    db.add_all([account, page, snapshot, template])
    db.commit()
    return account, snapshot, template


def test_graph_fetch_reads_all_identity_and_page_pages_without_tokens(monkeypatch):
    client = object.__new__(MetaClient)
    calls = []
    def get(path, params):
        calls.append((path, dict(params)))
        assert "access_token" not in params["fields"]
        if path.startswith("act_"):
            if "after" not in params:
                return {"data": [{"id": "200", "username": "brand"}], "paging": {"next": "ignored-url", "cursors": {"after": "next"}}}
            return {"data": [{"id": "201", "username": "second"}]}
        return {"data": [{"id": "100", "instagram_business_account": {"id": "200"}}]}
    monkeypatch.setattr(client, "_get", get)
    rows = client.get_instagram_identities("123")
    assert rows == [{"id": "200", "username": "brand", "page_ids": ["100"]}, {"id": "201", "username": "second", "page_ids": []}]
    assert calls[1][1]["after"] == "next"


def test_connector_identity_endpoint_and_client_use_scoped_credentials(monkeypatch):
    from fb_connector.api import assets
    from services.fb_connector_client import FBConnectorClient
    from config.settings import settings
    monkeypatch.setattr(assets, "_client", lambda credential_id: SimpleNamespace(
        get_instagram_identities=lambda account_id: [{"id": "200", "username": "brand", "page_ids": ["100"]}]
    ) if credential_id == "credential-1" else None)
    result = assets.list_instagram_identities(assets.AudienceListRequest(credential_id="credential-1", account_id="123"))
    assert result["account_id"] == "123" and result["items"][0]["id"] == "200"
    client = FBConnectorClient(base_url="https://connector.invalid", signing_key="test-only")
    calls = []
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: calls.append((args, kwargs)) or result)
    assert client.list_instagram_accounts("123", "credential-1") == result
    assert calls[0][0] == ("POST", "/internal/meta/instagram/list", {"account_id": "123", "credential_id": "credential-1"})
    assert calls[0][1]["timeout"] == settings.FB_CONNECTOR_REPORT_TIMEOUT


def test_connector_identity_failure_does_not_expose_private_details(monkeypatch):
    from fb_connector.api import assets
    def fail(account_id): raise RuntimeError("private-response")
    monkeypatch.setattr(assets, "_client", lambda _: SimpleNamespace(get_instagram_identities=fail))
    with pytest.raises(HTTPException) as error:
        assets.list_instagram_identities(assets.AudienceListRequest(credential_id="credential-1", account_id="123"))
    assert "private-response" not in error.value.detail


@pytest.mark.parametrize("paging", [{"next": "url"}, {"next": "url", "cursors": {"after": "repeated"}}])
def test_graph_partial_pagination_is_rejected(monkeypatch, paging):
    client = object.__new__(MetaClient)
    monkeypatch.setattr(client, "_get", lambda *args: {"data": [], "paging": paging})
    with pytest.raises(ValueError, match="分页不完整"):
        client.get_instagram_identities("123")


def test_sync_whitelists_metadata_and_empty_sync_revokes_identity(db, monkeypatch):
    account, snapshot, template = seed(db)
    rows = [{"id": "201", "username": "new", "page_ids": ["100"], "access_token": "never-store"}]
    monkeypatch.setattr("services.meta_instagram_service.FBConnectorClient", lambda: SimpleNamespace(list_instagram_accounts=lambda *args: {"items": rows}))
    result = MetaInstagramSyncService(db).sync_account(account.id)
    assert result["count"] == 1
    assert snapshot.items == [{"id": "201", "username": "new", "page_ids": ["100"]}]
    assert instagram_account_access_error(db, account, template.creative_config_json)
    rows.clear()
    assert MetaInstagramSyncService(db).sync_account(account.id)["count"] == 0
    assert snapshot.items == [] and snapshot.status == "HEALTHY"


def test_sync_failure_preserves_old_metadata_but_blocks_publish(db, monkeypatch):
    account, snapshot, template = seed(db)
    def fail(*args):
        raise RuntimeError("private remote response")
    monkeypatch.setattr("services.meta_instagram_service.FBConnectorClient", lambda: SimpleNamespace(list_instagram_accounts=fail))
    with pytest.raises(RuntimeError):
        MetaInstagramSyncService(db).sync_account(account.id)
    assert snapshot.items[0]["id"] == "200"
    assert snapshot.status == "ERROR" and "private" not in snapshot.last_sync_error
    assert "ERROR" in instagram_account_access_error(db, account, template.creative_config_json)


@pytest.mark.parametrize("change", ["stale", "auth", "error", "removed", "page", "page_permission", "missing"])
def test_selected_identity_rejects_stale_changed_or_unauthorized_snapshot(db, change):
    account, snapshot, template = seed(db)
    assert instagram_account_access_error(db, account, template.creative_config_json) is None
    if change == "stale": snapshot.last_synced_at = datetime.utcnow() - timedelta(hours=25)
    if change == "auth": account.connector_credential_id = "replacement"
    if change == "error": snapshot.status = "ERROR"
    if change == "removed": snapshot.items = []
    if change == "page": snapshot.items = [{"id": "200", "username": "brand", "page_ids": ["other"]}]
    if change == "page_permission": db.query(MetaPage).first().tasks = ["ANALYZE"]
    if change == "missing": db.delete(snapshot)
    db.flush()
    assert instagram_account_access_error(db, account, template.creative_config_json)
    # 未指定 Instagram 的现有投放不要求增加身份或同步动作。
    assert instagram_account_access_error(db, account, {"page_id": "100", "creatives": [{}]}) is None


def test_list_is_local_scoped_and_reports_multi_account_membership(db, monkeypatch):
    account, snapshot, _ = seed(db)
    db.add(AdAccount(id="ig-second", account_id="act_124", connector_credential_id="ig-credential"))
    db.add(MetaInstagramSnapshot(id="ig-second-snapshot", ad_account_id="ig-second", credential_id="ig-credential",
        status="HEALTHY", items=[], last_synced_at=datetime.utcnow()))
    db.commit()
    def unexpected(*args, **kwargs): raise AssertionError("list must not call Meta")
    monkeypatch.setattr("requests.sessions.Session.request", unexpected)
    admin = User(id="ig-admin", role="tenant_admin", tenant_id="test_tenant")
    result = list_instagram_identities("100", [account.id, "ig-second"], db, admin)
    assert result["source"] == "LOCAL_SNAPSHOT"
    assert result["items"][0]["account_ids"] == [account.id]
    assert len(result["accounts"]) == 2
    with pytest.raises(HTTPException) as denied:
        list_instagram_identities("100", [account.id], db, User(id="unassigned", role="user", tenant_id="test_tenant"))
    assert denied.value.status_code == 403
    with tenant_scope("other-tenant"), pytest.raises(HTTPException) as hidden:
        list_instagram_identities("100", [account.id], db, admin)
    assert hidden.value.status_code == 404


@pytest.mark.parametrize("mode", ["image", "video", "carousel", "legacy", "override"])
def test_payload_propagates_modern_identity_to_all_creative_formats(db, mode):
    _, _, template = seed(db)
    config = dict(template.creative_config_json)
    if mode == "legacy":
        config["instagram_actor_id"] = config.pop("instagram_user_id")
    if mode == "video":
        config["creatives"] = [{"asset_type": "video", "video_id": "video-1", "thumbnail_hash": "cover", "landing_url": "https://example.com"}]
    if mode == "carousel":
        config["creative_format"] = "CAROUSEL"
        config["carousel_cards"] = [config["creatives"][0], {**config["creatives"][0], "image_hash": "second"}]
    if mode == "override":
        config["creatives"] = [{**config["creatives"][0], "instagram_user_id": "201"}]
    template.creative_config_json = config
    payload = build_connector_payload(template, "act_123")
    story = payload["adsets"][0]["creatives"][0]["object_story_spec"]
    assert story["instagram_user_id"] == ("201" if mode == "override" else "200")
    assert "instagram_actor_id" not in story
    assert instagram_references(config) == [("100", story["instagram_user_id"])]


@pytest.mark.parametrize("config", [
    {"instagram_user_id": "200", "instagram_actor_id": "201"},
    {"instagram_user_id": "invalid"}, {"instagram_actor_id": "   "},
])
def test_invalid_or_conflicting_identity_fields_are_rejected(config):
    with pytest.raises(ValueError): instagram_references(config)


def test_direct_config_retains_identity(db):
    from api.jobs import _ensure_template
    from tests.test_jobs_api import _direct_request
    template_id = _ensure_template(db, _direct_request(instagram_user_id="200"), "test_tenant")
    assert db.get(CampaignTemplate, template_id).creative_config_json["instagram_user_id"] == "200"


@pytest.mark.parametrize("carousel", [True, False])
def test_adset_identity_overrides_root_for_inherited_creatives(db, carousel):
    _, _, template = seed(db)
    config = dict(template.creative_config_json)
    config["adsets"] = [{"instagram_user_id": "201"}]
    if carousel:
        config["creative_format"] = "CAROUSEL"
        config["carousel_cards"] = [config["creatives"][0], config["creatives"][0]]
    else:
        config["creatives"] = [{**config["creatives"][0]}]
    template.creative_config_json = config
    story = build_connector_payload(template, "act_123")["adsets"][0]["creatives"][0]["object_story_spec"]
    assert story["instagram_user_id"] == "201"
    assert instagram_references(config) == [("100", "201")]


def test_preflight_and_submission_revalidate_changed_identity(db, monkeypatch):
    account, snapshot, template = seed(db)
    monkeypatch.setattr("services.meta.AdAccountService.filter_available_ids", lambda *args, **kwargs: ([account.id], []))
    snapshot.items = []
    db.commit()
    result = JobService(db).preflight_campaign(template.id, [account.id])
    assert result["passed"] is False
    assert "Instagram" in result["accounts"][0]["reason"]
    with pytest.raises(ValueError, match="Instagram"):
        JobService(db).create_job(template_id=template.id, ad_account_ids=[account.id])
    assert db.query(CampaignJob).count() == 0


def test_dry_run_revalidates_identity_without_network(db, monkeypatch):
    from models import PublishPreview
    from services.delivery_dry_run import build_delivery_dry_run
    account, snapshot, template = seed(db)
    snapshot.items = []
    preview = PublishPreview(id="ig-preview", account_ids=[account.id], request_snapshot={}, result_snapshot={})
    def unexpected(*args, **kwargs): raise AssertionError("Dry Run must be local")
    monkeypatch.setattr("requests.sessions.Session.request", unexpected)
    result = build_delivery_dry_run(db, preview, template)
    assert result["passed"] is False and "Instagram" in result["errors"][0]["message"]


def test_sync_record_exists_before_dispatch_and_queue_failure_is_visible(db, monkeypatch):
    account, _, _ = seed(db)
    admin = User(id="ig-admin", role="tenant_admin", tenant_id="test_tenant")
    def enqueue(*, args, task_id):
        assert db.get(AsyncTaskRecord, task_id).status == "PENDING"
        assert args == [account.id]
        raise RuntimeError("broker unavailable")
    monkeypatch.setattr("api.meta_instagram.sync_instagram_task.apply_async", enqueue)
    with pytest.raises(HTTPException) as failure:
        sync_instagram_identities(account.id, db, admin)
    assert failure.value.status_code == 503
    record = db.query(AsyncTaskRecord).first()
    assert record.status == "FAILURE"
    # 共享同一账户的管理员可以查询资产同步任务，不依赖发起人身份。
    assert instagram_sync_status(record.task_id, db, User(id="second-admin", role="tenant_admin"))["state"] == "FAILURE"
    with pytest.raises(HTTPException): instagram_sync_status(record.task_id, db, User(id="unassigned", role="user"))


def test_worker_rejects_revoked_identity_before_any_remote_creation(db, monkeypatch):
    import tasks.campaign_tasks as tasks
    account, snapshot, template = seed(db)
    snapshot.items = []
    job = CampaignJob(id="ig-job", template_id=template.id)
    item = CampaignJobItem(id="ig-item", job_id=job.id, ad_account_id=account.id)
    db.add_all([job, item]); db.commit()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(tasks, "_validate_item_actor", lambda *args: False)
    monkeypatch.setattr(tasks, "_acquire_account_write_lock", lambda *args: None)
    monkeypatch.setattr(tasks, "_finalize_job_if_done", lambda *args: None)
    def unexpected(*args, **kwargs): raise AssertionError("revoked identity must never reach Connector")
    monkeypatch.setattr("requests.sessions.Session.request", unexpected)
    result = tasks.create_campaign_for_account.run.__wrapped__(SimpleNamespace(), item.id)
    assert "Instagram" in result["error"]
    assert item.error_code == "INSTAGRAM_IDENTITY_UNAVAILABLE"


def test_instagram_migration_upgrade_downgrade_and_postgres_ddl():
    migration = importlib.import_module("migrations.versions.0071_instagram_identity")
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for name in ("tenants", "ad_accounts"):
        Table(name, metadata, Column("id", String(50), primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        assert "meta_instagram_snapshots" in inspect(connection).get_table_names()
        assert inspect(connection).get_unique_constraints("meta_instagram_snapshots")[0]["column_names"] == ["tenant_id", "ad_account_id"]
        migration.downgrade()
        assert "meta_instagram_snapshots" not in inspect(connection).get_table_names()
    import io
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
        migration.downgrade()
    assert "CREATE TABLE meta_instagram_snapshots" in output.getvalue()
    assert "DROP TABLE meta_instagram_snapshots" in output.getvalue()
    engine.dispose()
