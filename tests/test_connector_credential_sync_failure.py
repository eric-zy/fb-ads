import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from fb_connector.api import campaigns as connector_api
from fb_connector.credential_store import ConnectorCredentialUnavailable, DatabaseCredentialVault, _cipher
from fb_connector.models import ConnectorCredential
from models import AdAccount, AdSetInstance, CampaignInstance, CampaignTemplate, SyncAlert, Tenant
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from tasks import meta_sync_tasks


@pytest.fixture
def vault(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    ConnectorCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        for status in ("ACTIVE", "EXPIRED", "INVALID", "DISABLED"):
            session.add(ConnectorCredential(id=status, app_id="test", status="ACTIVE" if status == "EXPIRED" else status,
                access_token_encrypted=_cipher().encrypt(b"never-expose-this-token").decode(),
                expires_at=datetime.utcnow() + timedelta(days=-1 if status == "EXPIRED" else 30)))
        session.commit()
    monkeypatch.setattr("fb_connector.credential_store.connector_session_factory", factory)
    yield DatabaseCredentialVault()
    engine.dispose()


@pytest.mark.parametrize("status", ["MISSING", "EXPIRED", "INVALID", "DISABLED"])
def test_vault_classifies_without_exposing_tokens(vault, status):
    with pytest.raises(ConnectorCredentialUnavailable) as caught:
        vault.get_access_token(status)
    assert caught.value.status == status
    assert caught.value.credential_id == status
    assert "never-expose" not in str(caught.value.detail())
    assert isinstance(caught.value, KeyError)  # Existing OAuth callers retain compatibility.


@pytest.mark.parametrize("status", ["MISSING", "EXPIRED", "INVALID", "DISABLED"])
@pytest.mark.parametrize("endpoint", ["list_campaigns", "list_adsets", "list_ads"])
def test_list_endpoints_return_structured_credential_errors(vault, monkeypatch, status, endpoint):
    meta = Mock(side_effect=AssertionError("Meta must not be called without a usable credential"))
    monkeypatch.setattr("services.meta.service.MetaAdsService", meta)
    payload = (connector_api.CampaignListRequest(account_id="act_test", credential_id=status)
               if endpoint == "list_campaigns" else connector_api.ParentRequest(parent_id="parent", credential_id=status))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(getattr(connector_api, endpoint)(payload))
    assert caught.value.status_code == 409
    assert caught.value.detail["credential_status"] == status
    assert caught.value.detail["credential_id"] == status
    meta.assert_not_called()


def test_valid_vault_still_decrypts(vault):
    assert vault.get_access_token("ACTIVE") == "never-expose-this-token"


def test_read_only_diagnostic_checks_references_without_token_fields(vault):
    from fb_connector.credential_store import connector_session_factory
    from scripts.check_connector_credentials import credential_states
    with connector_session_factory() as db:
        result = credential_states(db, ["ACTIVE", "MISSING", "EXPIRED", "ACTIVE"], limit=1)
    assert result["matched_records"] == 2
    assert not result["truncated"]
    assert {item["credential_id"]: item["status"] for item in result["items"]} == {
        "ACTIVE": "ACTIVE", "MISSING": "MISSING", "EXPIRED": "EXPIRED",
    }
    assert "token" not in str(result) and "encrypted" not in str(result)


def test_client_recognizes_structured_error(monkeypatch):
    detail = ConnectorCredentialUnavailable("missing", "MISSING").detail()
    monkeypatch.setattr("services.fb_connector_client.requests.request", lambda *_a, **_kw: SimpleNamespace(
        status_code=409, headers={}, json=lambda: {"detail": detail},
    ))
    with pytest.raises(FBConnectorError) as caught:
        FBConnectorClient(base_url="https://connector.test", signing_key="test-key").list_adsets("parent", "missing")
    assert caught.value.credential_unavailable
    assert caught.value.detail == detail
    assert str(caught.value) == detail["message"]


@pytest.mark.parametrize("message,status,expected", [
    ("'凭据不存在或已失效'", 400, True), ("invalid service signature", 401, False),
    ("provider timeout", 503, False), ("invalid payload", 400, False),
])
def test_old_connector_and_transport_errors_are_distinguished(message, status, expected):
    assert FBConnectorError(message, status_code=status, detail=message).credential_unavailable is expected


def test_malformed_error_code_is_not_a_credential_failure():
    assert not FBConnectorError("malformed", status_code=409, detail={"code": []}).credential_unavailable


@pytest.fixture
def sync_context(monkeypatch):
    # Real committed transactions verify rollback leaves local delivery state intact.
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Tenant(id="test_tenant", name="Test", slug="test-sync-credential"))
    account = AdAccount(id="failure-account", account_id="act_failure")
    db.add(account); db.flush()
    for index in (1, 2):
        template = CampaignTemplate(id=f"failure-template-{index}", name="Test")
        db.add(template); db.flush()
        campaign = CampaignInstance(id=f"failure-c{index}", template_id=template.id, ad_account_id=account.id,
            meta_campaign_id=f"remote-c{index}", name="Original", status="ACTIVE", meta_status="ACTIVE")
        db.add(campaign); db.flush()
        db.add(AdSetInstance(id=f"failure-g{index}", campaign_instance_id=campaign.id,
            meta_adset_id=f"remote-g{index}", name="Original", status="ACTIVE", meta_status="ACTIVE"))
    db.commit()
    monkeypatch.setattr(meta_sync_tasks, "SessionLocal", lambda: db)
    original_close = db.close
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(meta_sync_tasks, "CredentialResolver", lambda _db: SimpleNamespace(for_account=lambda _id: SimpleNamespace(credential_id="bad-credential")))
    release = Mock()
    monkeypatch.setattr(meta_sync_tasks.redis_client, "redis_client", SimpleNamespace(lock=lambda *_a, **_kw: SimpleNamespace(acquire=lambda **_kw: True, release=release)))
    notify = Mock()
    monkeypatch.setattr(meta_sync_tasks, "NotificationService", lambda: SimpleNamespace(notify_all=notify))
    monkeypatch.setattr("services.report_sync.sync_canonical_hierarchy", lambda *_a, **_kw: {})
    yield db, account, release, notify
    original_close(); engine.dispose()


@pytest.mark.parametrize("stage", ["campaigns", "adsets", "ads"])
@pytest.mark.parametrize("legacy", [False, True])
def test_unavailable_credential_stops_fanout_and_retries_and_preserves_state(sync_context, monkeypatch, stage, legacy):
    db, account, release, notify = sync_context
    detail = "'凭据不存在或已失效'" if legacy else ConnectorCredentialUnavailable("bad-credential", "MISSING").detail()
    failure = FBConnectorError("credential unavailable", status_code=400 if legacy else 409, detail=detail)
    connector = SimpleNamespace(
        list_campaigns=Mock(return_value={"campaigns": [{"id": f"remote-c{i}", "name": "Changed", "status": "PAUSED"} for i in (1, 2)]}),
        list_adsets=Mock(return_value={"adsets": [{"id": "remote-g1", "status": "PAUSED"}]}),
        list_ads=Mock(return_value={"ads": []}),
    )
    getattr(connector, "list_" + stage).side_effect = failure
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    task = SimpleNamespace(retry=Mock(side_effect=AssertionError("Credential failures must not retry")))
    for _ in range(2):
        result = meta_sync_tasks.sync_delivery_objects_task.run.__wrapped__(task, account.id)
        assert result["status"] == "failed"
        assert result["error_code"] == "CONNECTOR_CREDENTIAL_UNAVAILABLE"
    task.retry.assert_not_called()
    assert getattr(connector, "list_" + stage).call_count == 2  # One call per run, not per campaign.
    if stage == "campaigns":
        connector.list_adsets.assert_not_called(); connector.list_ads.assert_not_called()
    if stage == "adsets":
        connector.list_ads.assert_not_called()
    assert all(row.status == "ACTIVE" and row.name == "Original" for row in db.query(CampaignInstance).all())
    assert all(row.status == "ACTIVE" for row in db.query(AdSetInstance).all())
    assert db.query(SyncAlert).filter_by(alert_type="DELIVERY_SYNC_CREDENTIAL").count() == 1
    notify.assert_called_once()
    assert release.call_count == 2


def test_credential_alert_closes_after_successful_sync(sync_context, monkeypatch):
    db, account, _, _ = sync_context
    connector = SimpleNamespace(list_campaigns=Mock(side_effect=FBConnectorError(
        "凭据不存在或已失效", status_code=400)),
        list_adsets=lambda parent, _credential: {"adsets": [{"id": parent.replace("-c", "-g"), "status": "ACTIVE"}]},
        list_ads=lambda *_: {"ads": []})
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    task = SimpleNamespace(retry=Mock(side_effect=AssertionError("Unexpected retry")))
    assert meta_sync_tasks.sync_delivery_objects_task.run.__wrapped__(task, account.id)["status"] == "failed"
    connector.list_campaigns.side_effect = None
    connector.list_campaigns.return_value = {"campaigns": [{"id": f"remote-c{i}", "status": "ACTIVE"} for i in (1, 2)]}
    assert meta_sync_tasks.sync_delivery_objects_task.run.__wrapped__(task, account.id)["status"] == "success"
    assert db.query(SyncAlert).filter_by(alert_type="DELIVERY_SYNC_CREDENTIAL").one().is_resolved
