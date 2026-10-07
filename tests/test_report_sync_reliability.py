from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import importlib
import io

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import Base
from models import Tenant, AdAccount, AccountInsight, Campaign, AdGroup, Ad, CampaignInsight, AdSetInsight, AdInsight, ReportSyncRun, User, AsyncTaskRecord
from services.ads_manager import AdsManager
from services.report_quality import report_quality
from services.report_sync import sync_report_window
from services.meta.service import MetaAdsService
from services.meta.errors import MetaApiError


@pytest.fixture
def committed_db():
    # Independent transactions exercise rollback without rolling back fixtures.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Tenant(id="test_tenant", name="Tests", slug="tests"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def report_context(committed_db, monkeypatch):
    account = AdAccount(id="reliable-report-account", account_id="act_123", currency="USD", system_status="DISABLED")
    committed_db.add(account)
    committed_db.commit()
    day = str(date.today())
    common = {"date_start": day, "date_stop": day, "account_id": "123", "spend": "10.50", "impressions": "100", "clicks": "10"}
    rows = {"account": [common], "campaign": [{**common, "campaign_id": "c1"}],
            "adset": [{**common, "campaign_id": "c1", "adset_id": "g1"}],
            "ad": [{**common, "campaign_id": "c1", "adset_id": "g1", "ad_id": "a1"}]}
    connector = SimpleNamespace(
        get_insights=Mock(side_effect=lambda *args, level, **kwargs: {"items": rows[level], "complete": True, "time_increment": 1}),
        list_campaigns=Mock(return_value={"campaigns": [{"id": "c1", "name": "External campaign", "status": "ACTIVE"}]}),
        list_adsets=Mock(return_value={"adsets": [{"id": "g1", "name": "External group", "status": "ACTIVE", "daily_budget": "2000"}]}),
        list_ads=Mock(return_value={"ads": [{"id": "a1", "name": "External ad", "status": "ACTIVE"}]}),
    )
    for module in ("services.ads_manager", "services.report_sync"):
        monkeypatch.setattr(module + ".FBConnectorClient", lambda: connector)
        monkeypatch.setattr(module + ".CredentialResolver", lambda db: SimpleNamespace(for_account=lambda id: SimpleNamespace(credential_id="test")))
    return committed_db, account, rows, connector


def test_all_four_levels_include_external_objects_and_local_disabled_account(report_context):
    db, account, _, connector = report_context
    today = date.today()
    result = sync_report_window(db, account, today, today, "task-id")
    assert result["delivery_counts"] == {"campaign": 1, "adset": 1, "ad": 1}
    assert result["hierarchy_counts"] == {"campaign": 1, "adset": 1, "ad": 1}
    for model in (AccountInsight, CampaignInsight, AdSetInsight, AdInsight):
        assert db.query(model).one().spend == 1050
    assert connector.get_insights.call_count == 4
    assert report_quality(db, account, today, today)["status"] == "FRESH"
    assert db.query(ReportSyncRun).one().snapshots["ad"][0]["ad_id"] == "a1"


def test_unmapped_delivery_row_fails_whole_window_and_keeps_previous_financial_data(report_context):
    db, account, rows, _ = report_context
    old = AccountInsight(id="old-spend", ad_account_id=account.id, date=date.today(), spend=500, revenue=900)
    db.add(old)
    db.commit()
    rows["ad"][0]["ad_id"] = "missing-ad"
    with pytest.raises(ValueError, match="缺少账户内映射"):
        sync_report_window(db, account, date.today(), date.today())
    assert db.query(AccountInsight).one().spend == 500
    assert db.query(AccountInsight).one().revenue == 900
    assert db.query(CampaignInsight).count() == 0
    assert db.query(Campaign).count() == 0
    run = db.query(ReportSyncRun).one()
    assert run.status == "FAILED"
    assert run.snapshots["ad"][0]["ad_id"] == "missing-ad"
    assert report_quality(db, account, date.today(), date.today())["status"] == "NEVER"


def test_complete_empty_snapshot_replaces_old_metrics_but_preserves_imported_income(report_context):
    db, account, rows, _ = report_context
    db.add(AccountInsight(id="old-empty-spend", ad_account_id=account.id, date=date.today(), spend=500, revenue=900, clicks=5))
    db.commit()
    for level in rows:
        rows[level] = []
    result = sync_report_window(db, account, date.today(), date.today())
    insight = db.query(AccountInsight).one()
    assert result["insights_count"] == 0
    assert insight.spend == insight.clicks == 0
    assert insight.revenue == insight.profit == 900
    assert report_quality(db, account, date.today(), date.today())["complete"] is True


@pytest.mark.parametrize("change", [
    {"date_stop": "2026-01-02"}, {"date_start": "bad"}, {"account_id": "456"},
])
def test_daily_validation_rejects_aggregate_bad_date_and_other_account(change):
    account = AdAccount(account_id="act_123")
    rows = [{"date_start": "2026-01-01", "date_stop": "2026-01-01", "account_id": "123", **change}]
    with pytest.raises(ValueError):
        AdsManager._validate_daily_rows(rows, "2026-01-01", "2026-01-03", account)


def test_daily_validation_rejects_duplicate_and_outside_window():
    row = {"date_start": "2026-01-01", "date_stop": "2026-01-01"}
    with pytest.raises(ValueError, match="重复"):
        AdsManager._validate_daily_rows([row, row], "2026-01-01", "2026-01-01", AdAccount())
    with pytest.raises(ValueError, match="窗口"):
        AdsManager._validate_daily_rows([row], "2026-01-02", "2026-01-03", AdAccount())


def test_old_connector_cannot_mark_aggregate_rows_complete(report_context):
    db, account, _, connector = report_context
    connector.get_insights.side_effect = None
    connector.get_insights.return_value = {"items": []}
    with pytest.raises(ValueError, match="先升级海外 Connector"):
        sync_report_window(db, account, date.today(), date.today())


def test_quality_uses_complete_window_instead_of_account_metadata(committed_db):
    db = committed_db
    today = date.today()
    account = AdAccount(id="quality-account", account_id="act_quality", last_synced_at=datetime.utcnow(),
                        insights_last_synced_at=datetime.utcnow(), insights_sync_status="SUCCESS")
    db.add(account)
    db.commit()
    assert report_quality(db, account, today, today)["status"] == "NEVER"
    db.add(ReportSyncRun(id="quality-run", account_id=account.id, start_date=today, end_date=today,
                         status="SUCCESS", snapshots={"account": []}, finished_at=datetime.utcnow()))
    db.commit()
    assert report_quality(db, account, today - timedelta(days=29), today)["status"] == "INCOMPLETE"
    assert report_quality(db, account, today, today, "ad")["status"] == "NEVER"
    account.insights_sync_status = "FAILED"
    assert report_quality(db, account, today, today)["status"] == "FAILED"


def test_report_task_ownership_committed_before_dispatch_and_queue_failure_visible(db, monkeypatch):
    from api.reports import sync_report_data
    account = AdAccount(id="queued-report-account", account_id="act_queued", system_status="DISABLED")
    admin = User(id="queued-report-admin", username="queued-report-admin", email="queue@test.local", hashed_password="unused", role="tenant_admin")
    db.add_all([account, admin]); db.commit()
    def dispatch(*, args, kwargs, task_id):
        assert db.query(AsyncTaskRecord).filter_by(task_id=task_id).one().created_by == admin.id
        assert kwargs == {"start_date": "2026-01-01", "end_date": "2026-01-30"}
        raise RuntimeError("broker unavailable")
    monkeypatch.setattr("api.reports.fetch_account_insights", SimpleNamespace(apply_async=dispatch))
    result = sync_report_data(account_id=account.id, days=30, start_date=date(2026, 1, 1), end_date=date(2026, 1, 30), db=db, current_user=admin)
    assert result["status"] == "partial_failure"
    assert db.query(AsyncTaskRecord).one().status == account.insights_sync_status == "FAILED"
    assert db.query(AsyncTaskRecord).one().result_summary["start_date"] == "2026-01-01"


def test_explicit_sync_window_overrides_default_days_and_is_auditable(db, monkeypatch):
    from api.reports import sync_report_data
    from models import AuditLog
    account = AdAccount(id="window-audit-account", account_id="act_window_audit")
    admin = User(id="window-audit-admin", username="window-audit-admin", email="window-audit@test.local", hashed_password="unused", role="tenant_admin")
    db.add_all([account, admin]); db.commit()
    dispatched = []
    def dispatch(*, args, kwargs, task_id):
        dispatched.append((args, kwargs))
        assert db.query(AsyncTaskRecord).filter_by(task_id=task_id).one().result_summary["days"] == 30
    monkeypatch.setattr("api.reports.fetch_account_insights", SimpleNamespace(apply_async=dispatch))
    result = sync_report_data(account_id=account.id, days=3, start_date=date(2026, 1, 1), end_date=date(2026, 1, 30), db=db, current_user=admin)
    assert result["days"] == 30
    assert result["start_date"] == "2026-01-01"
    assert dispatched[0][0] == [account.id, 30]
    log = db.query(AuditLog).filter_by(action="SYNC_REPORT_DATA", resource_id=account.id).one()
    assert log.request_data["days"] == 30
    assert log.request_data["end_date"] == "2026-01-30"


def test_successful_database_report_record_remains_queryable_when_celery_result_expired(db, monkeypatch):
    from api.campaigns import get_async_task_status
    admin = User(id="task-report-admin", role="tenant_admin")
    record = AsyncTaskRecord(task_id="abc123", task_type="REPORT_SYNC", created_by=admin.id, status="SUCCESS", result_summary={"status": "success"})
    db.add(record); db.commit()
    monkeypatch.setattr("api.campaigns.celery_app.AsyncResult", Mock(side_effect=AssertionError("should use durable record")))
    assert get_async_task_status("abc123", db, admin)["result"]["status"] == "success"


@pytest.mark.parametrize("receipt", [False, {"success": False}, {}, {"id": "object"}])
def test_meta_update_false_or_missing_ack_is_not_success(receipt):
    client = SimpleNamespace(_post=Mock(return_value=receipt), _get=Mock(return_value={"id": "object", "status": "ACTIVE"}))
    with pytest.raises(MetaApiError, match="success=true"):
        MetaAdsService(client, enable_rate_limit=False).update_ad("object", {"status": "PAUSED"})
    assert client._post.call_count == 1


def test_meta_update_distinguishes_configured_and_effective_status():
    client = SimpleNamespace(_post=Mock(return_value={"success": True}),
                             _get=Mock(side_effect=[{"status": "PAUSED"}, {"id": "object", "status": "ACTIVE", "effective_status": "CAMPAIGN_PAUSED"}]))
    result = MetaAdsService(client, enable_rate_limit=False).update_ad("object", {"status": "ACTIVE"})
    assert result["confirmed"] is True
    assert result["effective_status"] == "CAMPAIGN_PAUSED"


def test_meta_readback_mismatch_never_replays_acknowledged_post():
    client = SimpleNamespace(_post=Mock(return_value=True), _get=Mock(return_value={"id": "object", "status": "ACTIVE"}))
    with pytest.raises(MetaApiError, match="尚未确认"):
        MetaAdsService(client, enable_rate_limit=False).update_campaign("object", {"status": "PAUSED"})
    assert client._post.call_count == 1


@pytest.mark.parametrize("state", ["ARCHIVED", "DELETED"])
def test_meta_archived_object_rejected_before_write(state):
    client = SimpleNamespace(_post=Mock(), _get=Mock(return_value={"status": state}))
    with pytest.raises(MetaApiError, match="不能直接修改"):
        MetaAdsService(client, enable_rate_limit=False).update_ad("object", {"status": "ACTIVE"})
    client._post.assert_not_called()


def test_insights_reads_more_than_twenty_pages_and_ignores_terminal_cursor(monkeypatch):
    seen = []
    def read(url, *, params, timeout):
        page = len(seen) + 1
        seen.append(params)
        paging = {"cursors": {"after": str(page)}}
        if page < 25: paging["next"] = "https://graph.facebook.com/next"
        return SimpleNamespace(status_code=200, json=lambda: {"data": [{"page": page}], "paging": paging})
    monkeypatch.setattr("services.meta.service.requests.get", read)
    client = SimpleNamespace(normalize_account_id=lambda value: value, access_token="dummy")
    result = MetaAdsService(client, enable_rate_limit=False).get_insights("act_123", {"time_range": {"since": "2026-01-01", "until": "2026-01-03"}, "time_increment": "all_days"})
    assert len(result) == len(seen) == 25
    assert all(params["time_increment"] == 1 and "date_preset" not in params for params in seen)


def test_insights_invalid_response_or_repeated_cursor_fails(monkeypatch):
    payload = {"data": [], "paging": {"next": "next", "cursors": {"after": "same"}}}
    monkeypatch.setattr("services.meta.service.requests.get", lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: payload))
    client = SimpleNamespace(normalize_account_id=lambda value: value, access_token="dummy")
    with pytest.raises(MetaApiError, match="重复"):
        MetaAdsService(client, enable_rate_limit=False, max_retries=0).get_insights("act_123", {})


def test_report_window_migration_sqlite_roundtrip_and_postgres_ddl():
    migration = importlib.import_module("migrations.versions.0073_report_sync_runs")
    engine = create_engine("sqlite://")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        assert "report_sync_runs" in inspect(connection).get_table_names()
        migration.downgrade()
        assert "report_sync_runs" not in inspect(connection).get_table_names()
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
    assert "FOREIGN KEY(account_id) REFERENCES ad_accounts" in output.getvalue()


def test_busy_report_task_retries_without_overwriting_active_account_sync(committed_db, monkeypatch):
    from tasks import celery_tasks
    from celery.exceptions import Retry
    db = committed_db
    account = AdAccount(id="busy-report-account", account_id="act_busy", insights_sync_status="SYNCING")
    db.add(account); db.commit()
    monkeypatch.setattr(celery_tasks, "SessionLocal", lambda: SimpleNamespace(query=db.query, commit=db.commit, rollback=db.rollback, close=lambda: None))
    monkeypatch.setattr(celery_tasks.redis_client, "redis_client", SimpleNamespace(lock=lambda *args, **kwargs: SimpleNamespace(acquire=lambda **kwargs: False)))
    task = SimpleNamespace(request=SimpleNamespace(id="busy-task", retries=0), max_retries=3, retry=Mock(side_effect=Retry()))
    with pytest.raises(Retry):
        celery_tasks.fetch_account_insights.run.__wrapped__(task, account.id)
    assert db.query(AdAccount).one().insights_sync_status == "SYNCING"
    task.retry.assert_called_once()


def test_periodic_collection_includes_locally_disabled_accounts_and_staggers_queue(db, monkeypatch):
    from tasks import celery_tasks
    db.add_all([AdAccount(id=f"periodic-{status}", account_id=f"act_{status}", system_status=status) for status in ("ACTIVE", "DISABLED")])
    db.commit()
    monkeypatch.setattr(celery_tasks, "SessionLocal", lambda: SimpleNamespace(query=db.query, close=lambda: None))
    dispatch = Mock(return_value=SimpleNamespace(id="periodic-task"))
    monkeypatch.setattr(celery_tasks, "fetch_account_insights", SimpleNamespace(apply_async=dispatch))
    result = celery_tasks.fetch_all_accounts_insights.run.__wrapped__(SimpleNamespace(), 3)
    assert result["task_count"] == 2
    assert {call.kwargs["args"][0] for call in dispatch.call_args_list} == {"periodic-ACTIVE", "periodic-DISABLED"}
    assert sorted(call.kwargs["countdown"] for call in dispatch.call_args_list) == [0, 5]


def test_risk_pause_projects_canonical_status_to_matching_instance(db):
    from models import CampaignInstance, CampaignTemplate
    from services.meta_updates import project_status
    account = AdAccount(id="project-account", account_id="act_project")
    template = CampaignTemplate(id="project-template", name="Project template")
    canonical = Campaign(id="project-canonical", campaign_id="project-remote", name="Project", ad_account_id=account.id)
    instance = CampaignInstance(id="project-instance", meta_campaign_id=canonical.campaign_id, template_id=template.id, ad_account_id=account.id, status="ACTIVE")
    db.add_all([account, template, canonical, instance]); db.commit()
    project_status(db, account.id, "CAMPAIGN", canonical.campaign_id, "PAUSED", "PAUSED")
    assert canonical.status.value == instance.status == instance.meta_status == "PAUSED"


def test_generic_recovery_does_not_dispatch_risk_engine_actions(db, monkeypatch):
    from models import DeliveryAction
    from tasks.recovery_tasks import _recover_delivery_actions
    row = DeliveryAction(id="risk-recovery", account_id="unused", object_id="canonical-object", object_type="CAMPAIGN",
                         action="PAUSE", requested_by="risk-engine", status="RUNNING", idempotency_key="risk-recovery",
                         created_at=datetime.utcnow() - timedelta(days=1))
    db.add(row); db.commit()
    dispatch = Mock()
    monkeypatch.setattr("tasks.meta_sync_tasks.update_delivery_object_task", SimpleNamespace(apply_async=dispatch))
    assert _recover_delivery_actions(db, 10) == 0
    assert row.status == "RUNNING"
    dispatch.assert_not_called()


def test_legacy_analytics_uses_currency_and_exact_seven_day_week(db):
    from core.reporting_time import account_today
    from services.analytics import AnalyticsEngine
    account = AdAccount(id="weekly-jpy", account_id="act_weekly_jpy", currency="JPY", timezone="Asia/Tokyo")
    db.add(account); db.flush()
    today = account_today(account)
    for offset in range(8):
        db.add(AccountInsight(id=f"weekly-jpy-{offset}", ad_account_id=account.id, date=today - timedelta(days=offset), spend=1000,
                              clicks=10, impressions=100, conversions=1, conversion_value=2000))
    db.commit()
    engine = AnalyticsEngine(db)
    assert engine.generate_weekly_report(account.id, today)["total_metrics"]["spend"] == 7000
    assert engine.generate_weekly_report(account.id, today)["daily_count"] == 7
    assert engine.generate_daily_report(account.id, today)["metrics"]["spend"] == 1000
    assert engine.generate_daily_report(account.id, today)["metrics"]["roas"] == 2
