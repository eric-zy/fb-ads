from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime, timedelta
import importlib

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.campaigns import CampaignActionRequest, campaign_action, retry_delivery_action, OperationLeasePayload
from core.enums import ErrorCategory
from fb_connector.api import deletions
from fb_connector.models import ConnectorBase, ConnectorObjectDeletion
from models import AdAccount, AdInstance, AdSetInstance, CampaignInstance, CampaignTemplate, DeliveryAction, User, CampaignJob, CampaignJobItem
from services.account_operation_lease import AccountOperationLeaseService
from services.fb_connector_client import FBConnectorError
from services.meta.errors import MetaApiError
from tasks import meta_sync_tasks


@pytest.fixture
def context(db, monkeypatch):
    user = User(id="delete-admin", username="delete-admin", email="delete@test.local", hashed_password="unused", role="tenant_admin", tenant_id="test_tenant", is_active=True)
    account = AdAccount(id="delete-account", account_id="act_123", account_name="Delete account", tenant_id="test_tenant")
    template = CampaignTemplate(id="delete-template", name="Delete template", creative_config_json={})
    campaign = CampaignInstance(id="delete-campaign", template_id=template.id, ad_account_id=account.id,
                                meta_campaign_id="1001", name="Campaign", status="ACTIVE", meta_status="ACTIVE")
    adset = AdSetInstance(id="delete-adset", campaign_instance_id=campaign.id, meta_adset_id="1002", name="Adset", status="ACTIVE")
    ad = AdInstance(id="delete-ad", adset_instance_id=adset.id, meta_ad_id="1003", name="Ad", status="ACTIVE")
    db.add_all([user, account, template, campaign, adset, ad])
    db.flush()
    lease = AccountOperationLeaseService(db).acquire("test_tenant", account.id, user.id, "CAMPAIGN_ACTION")
    db.commit()
    monkeypatch.setattr("api.campaigns.update_delivery_object_task", SimpleNamespace(apply_async=Mock()))
    monkeypatch.setattr(meta_sync_tasks, "SessionLocal", lambda: SimpleNamespace(
        query=db.query, commit=db.commit, rollback=db.rollback, close=lambda: None))
    monkeypatch.setattr(meta_sync_tasks, "CredentialResolver", lambda db: SimpleNamespace(for_account=lambda id: SimpleNamespace(credential_id="credential")))
    monkeypatch.setattr(meta_sync_tasks.redis_client, "redis_client", SimpleNamespace(lock=lambda *args, **kwargs: SimpleNamespace(acquire=lambda **kwargs: True, release=lambda: None)))
    return user, account, campaign, adset, ad, lease


def submit(db, context, object_type="CAMPAIGN", target=None, action="DELETE", key="test-delete"):
    user, account, campaign, adset, ad, lease = context
    obj = target or {"CAMPAIGN": campaign, "ADSET": adset, "AD": ad}[object_type]
    result = campaign_action(CampaignActionRequest(action=action, object_type=object_type, ids=[obj.id],
                             operation_leases={account.id: lease.lease_token}, idempotency_key=key), db, user)
    return db.query(DeliveryAction).filter_by(id=result["action_ids"][0]).one()


def execute(row):
    return meta_sync_tasks.update_delivery_object_task.run.__wrapped__(SimpleNamespace(), row.object_type, row.object_id, row.account_id, row.action, row.id)


def test_delivery_sync_replaces_technical_names_and_preserves_archived_state(db, monkeypatch, context):
    _, account, campaign, adset, ad, _ = context
    campaign.name = "旧系列名称"
    adset.name = "adset-1"
    ad.name = "ad-1-1"
    ad.status = "ARCHIVED"
    db.commit()
    connector = SimpleNamespace(
        list_campaigns=lambda *args: {"campaigns": [{"id": "1001", "name": "远端系列", "status": "PAUSED"}]},
        list_adsets=lambda *args: {"adsets": [{"id": "1002", "name": "US 广告组", "status": "PAUSED"}]},
        list_ads=lambda *args: {"ads": [{"id": "1003", "name": "广告完整名称", "status": "PAUSED"}]},
    )
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    monkeypatch.setattr(meta_sync_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr("services.report_sync.FBConnectorClient", lambda: connector)
    monkeypatch.setattr("services.report_sync.CredentialResolver", meta_sync_tasks.CredentialResolver)
    result = meta_sync_tasks.sync_delivery_objects_task.run.__wrapped__(SimpleNamespace(), account.id)
    assert result["status"] == "success"
    assert campaign.name == "远端系列" and adset.name == "US 广告组" and ad.name == "广告完整名称"
    assert ad.status == "ARCHIVED"
    # A partial response must not blank names or replace them with an internal key.
    connector.list_ads = lambda *args: {"ads": [{"id": "1003", "status": "PAUSED"}]}
    meta_sync_tasks.sync_delivery_objects_task.run.__wrapped__(SimpleNamespace(), account.id)
    assert ad.name == "广告完整名称"


@pytest.mark.parametrize("object_type", ["CAMPAIGN", "ADSET", "AD"])
def test_real_delete_marks_state_only_after_meta_ack(db, monkeypatch, context, object_type):
    row = submit(db, context, object_type)
    obj = {"CAMPAIGN": context[2], "ADSET": context[3], "AD": context[4]}[object_type]
    assert obj.status == "ACTIVE"
    connector = SimpleNamespace(delete_object=Mock(return_value={"status": "SUCCESS", "remote_status": "DELETED"}), update_object=Mock())
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    result = execute(row)
    assert result["status"] == "success"
    assert obj.status == obj.meta_status == row.remote_status == "DELETED"
    assert row.status == "SUCCESS"
    assert connector.delete_object.call_args.args[0] == object_type
    assert connector.delete_object.call_args.kwargs["confirm_only"] is False
    connector.update_object.assert_not_called()
    if object_type == "CAMPAIGN":
        assert context[3].status == context[4].status == "DELETED"
    if object_type != "AD":
        assert context[4].meta_status == "PARENT_DELETED"
    # Deleting a child must never delete shared parent objects.
    if object_type in {"ADSET", "AD"}:
        assert context[2].status == "ACTIVE"
    if object_type == "AD":
        assert context[3].status == "ACTIVE"
    execute(row)
    assert connector.delete_object.call_count == 1


@pytest.mark.parametrize("response,expected", [
    ({"status": "FAILED", "error": "permission denied"}, "FAILED"),
    ({"status": "UNKNOWN", "error": "timeout"}, "UNKNOWN"),
])
def test_failure_or_unknown_never_hides_object(db, monkeypatch, context, response, expected):
    row = submit(db, context)
    connector = SimpleNamespace(delete_object=Mock(return_value=response))
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    execute(row)
    assert row.status == expected
    assert context[2].status == "ACTIVE"
    if expected == "UNKNOWN":
        connector.delete_object.return_value = {"status": "SUCCESS", "remote_status": "DELETED"}
        execute(row)
        assert connector.delete_object.call_args.kwargs["confirm_only"] is True
        assert row.status == "SUCCESS"


def test_transport_loss_is_unknown_and_legacy_removed_remains_retryable(db, monkeypatch, context):
    context[2].status = "DELETED"
    context[2].meta_status = "PAUSED"
    assert context[2].to_dict()["deletion_state"] == "LOCAL_REMOVED"
    row = submit(db, context)
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: SimpleNamespace(delete_object=Mock(side_effect=FBConnectorError("timeout"))))
    execute(row)
    assert row.status == "UNKNOWN"
    assert context[2].meta_status == "PAUSED"
    assert context[2].to_dict()["deletion_state"] == "LOCAL_REMOVED"


def test_restore_rejects_deleted_objects(db, context):
    context[2].status = "DELETED"
    with pytest.raises(HTTPException, match="只有本地归档"):
        submit(db, context, action="RESTORE")
    assert db.query(DeliveryAction).count() == 0


def test_archive_then_restore_keeps_meta_paused(db, monkeypatch, context):
    connector = SimpleNamespace(update_object=Mock(return_value={"result": {"confirmed": True, "status": "PAUSED"}}), delete_object=Mock())
    monkeypatch.setattr(meta_sync_tasks, "FBConnectorClient", lambda: connector)
    archived = submit(db, context, action="ARCHIVE", key="archive-test")
    execute(archived)
    assert archived.status == "SUCCESS"
    assert context[2].status == "ARCHIVED"
    assert context[2].meta_status == "PAUSED"
    assert context[2].archived_at is not None
    restored = submit(db, context, action="RESTORE", key="restore-test")
    execute(restored)
    assert restored.status == "SUCCESS"
    assert context[2].status == context[2].meta_status == "PAUSED"
    assert context[2].archived_at is None
    assert connector.update_object.call_count == 2
    assert all(call.args[3] == {"status": "PAUSED"} for call in connector.update_object.call_args_list)
    connector.delete_object.assert_not_called()


def test_wrong_object_type_does_not_fall_back_to_campaign(db, context):
    with pytest.raises(HTTPException) as exc:
        submit(db, context, "AD", target=context[2])
    assert exc.value.status_code == 404
    assert db.query(DeliveryAction).count() == 0


def test_enqueue_failure_is_visible_and_not_running(db, monkeypatch, context):
    monkeypatch.setattr("api.campaigns.update_delivery_object_task", SimpleNamespace(apply_async=Mock(side_effect=RuntimeError("queue down"))))
    row = submit(db, context)
    assert row.status == "FAILED"
    assert "入队失败" in row.error_message
    assert context[2].status == "ACTIVE"


@pytest.mark.parametrize("original_status,queue_fails", [("FAILED", False), ("UNKNOWN", False), ("UNKNOWN", True)])
def test_retry_or_reconcile_preserves_delete_semantics(db, monkeypatch, context, original_status, queue_fails):
    user, account, campaign, _, _, lease = context
    row = submit(db, context)
    row.status = original_status
    row.request_payload = {**row.request_payload, "delete_dispatched": True}
    db.commit()
    leases = AccountOperationLeaseService(db)
    leases.release(user.tenant_id, account.id, user.id, lease.lease_token)
    retry_lease = leases.acquire(user.tenant_id, account.id, user.id, "CAMPAIGN_RETRY")
    db.commit()
    if queue_fails:
        monkeypatch.setattr("api.campaigns.update_delivery_object_task", SimpleNamespace(apply_async=Mock(side_effect=RuntimeError("queue down"))))
    result = retry_delivery_action(row.id, OperationLeasePayload(lease_token=retry_lease.lease_token), db, user)
    retry_row = db.query(DeliveryAction).filter_by(id=result["action_id"]).one()
    assert retry_row.status == ("UNKNOWN" if queue_fails else "REQUESTED")
    if original_status == "UNKNOWN":
        assert retry_row.id == row.id
        assert retry_row.idempotency_key == row.idempotency_key
        assert retry_row.request_payload["delete_dispatched"] is True
        assert db.query(DeliveryAction).count() == 1
    else:
        assert retry_row.id != row.id
        assert retry_row.idempotency_key != row.idempotency_key
        assert retry_row.request_payload["delete_dispatched"] is False
    assert campaign.status == "ACTIVE"


@pytest.fixture
def overseas(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    ConnectorBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(deletions, "connector_session_factory", factory)
    service = SimpleNamespace(get_delivery_object=Mock(return_value={"id": "1001", "account_id": "123", "status": "PAUSED"}),
                              delete_object=Mock(return_value={"success": True}))
    monkeypatch.setattr(deletions, "_service", lambda id: service)
    monkeypatch.setattr(deletions, "report_meta_auth_failure", lambda *args: None)
    return service, factory


def request(**kwargs):
    return deletions.ObjectDeletionRequest(object_type="CAMPAIGN", object_id="1001", account_id="act_123",
                                           credential_id="credential", idempotency_key="receipt-001", **kwargs)


def test_connector_delete_receipt_survives_replay(overseas):
    service, factory = overseas
    result = deletions.delete_object(request())
    assert result["status"] == "SUCCESS"
    # Even if permissions are later lost, a persisted acknowledgment is enough.
    service.get_delivery_object.side_effect = RuntimeError("lost permission")
    assert deletions.delete_object(request(confirm_only=True))["status"] == "SUCCESS"
    service.delete_object.assert_called_once_with("1001")


def test_connector_unknown_is_reconciled_without_repeating_delete(overseas):
    service, factory = overseas
    service.delete_object.side_effect = MetaApiError("timeout", category=ErrorCategory.TEMPORARY)
    assert deletions.delete_object(request())["status"] == "UNKNOWN"
    service.get_delivery_object.side_effect = RuntimeError("not found or no permissions")
    assert deletions.delete_object(request(confirm_only=True))["status"] == "UNKNOWN"
    service.get_delivery_object.side_effect = None
    service.get_delivery_object.return_value = {"account_id": "123", "status": "DELETED"}
    assert deletions.delete_object(request(confirm_only=True))["status"] == "SUCCESS"
    assert service.delete_object.call_count == 1


def test_connector_read_only_check_and_account_scope(overseas):
    service, factory = overseas
    assert deletions.delete_object(request(confirm_only=True))["status"] == "NOT_DELETED"
    service.delete_object.assert_not_called()
    service.get_delivery_object.return_value = {"account_id": "456", "status": "PAUSED"}
    with pytest.raises(HTTPException) as exc:
        deletions.delete_object(request())
    assert exc.value.status_code == 409
    service.delete_object.assert_not_called()


def test_connector_rejects_false_success_and_definite_permission_failure(overseas):
    service, factory = overseas
    service.delete_object.return_value = {"success": False}
    assert deletions.delete_object(request())["status"] == "UNKNOWN"
    service.delete_object.side_effect = MetaApiError("denied", category=ErrorCategory.PERMISSION)
    other = request().model_copy(update={"idempotency_key": "receipt-002"})
    assert deletions.delete_object(other)["status"] == "FAILED"


def test_stale_worker_keeps_delete_checkpoint_for_read_only_recovery(db, monkeypatch, context):
    from tasks.recovery_tasks import _recover_delivery_actions
    row = submit(db, context)
    row.status = "RUNNING"
    row.request_payload = {"delete_dispatched": True}
    row.started_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    calls = Mock()
    monkeypatch.setattr(meta_sync_tasks.update_delivery_object_task, "apply_async", calls)
    assert _recover_delivery_actions(db, 100) == 1
    assert row.status == "REQUESTED"
    assert row.request_payload["delete_dispatched"] is True
    assert calls.call_args.kwargs["args"][-1] == row.id


def test_connector_receipt_migration_round_trip_and_postgres_ddl():
    import io
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    migration = importlib.import_module("fb_connector.migrations.versions.0010_object_deletions")
    engine = create_engine("sqlite://")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        assert "connector_object_deletions" in inspect(connection).get_table_names()
        migration.downgrade()
        assert "connector_object_deletions" not in inspect(connection).get_table_names()
    output = io.StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        migration.upgrade()
        migration.downgrade()
    assert "CREATE TABLE connector_object_deletions" in output.getvalue()


@pytest.mark.parametrize("status", ["SUCCESS", "UNKNOWN"])
def test_legacy_campaign_job_also_uses_real_delete(db, monkeypatch, context, status):
    from tasks import campaign_tasks
    user, account, campaign, *_ = context
    job = CampaignJob(id="legacy-delete-job", template_id=campaign.template_id, action_type="DELETE", created_by=user.id)
    item = CampaignJobItem(id="legacy-delete-item", job_id=job.id, ad_account_id=account.id, campaign_instance_id=campaign.id)
    db.add_all([job, item]); db.commit()
    monkeypatch.setattr(campaign_tasks, "SessionLocal", lambda: SimpleNamespace(query=db.query, commit=db.commit, rollback=db.rollback, close=lambda: None))
    monkeypatch.setattr(campaign_tasks, "_validate_item_actor", lambda *args: False)
    monkeypatch.setattr(campaign_tasks, "_acquire_account_write_lock", lambda *args: None)
    monkeypatch.setattr(campaign_tasks, "_finalize_job_if_done", lambda *args: None)
    monkeypatch.setattr(campaign_tasks, "CredentialResolver", lambda db: SimpleNamespace(for_job_item=lambda item: SimpleNamespace(credential_id="credential")))
    connector = SimpleNamespace(delete_object=Mock(return_value={"status": status, "remote_status": "DELETED" if status == "SUCCESS" else None}), update_object=Mock())
    monkeypatch.setattr(campaign_tasks, "FBConnectorClient", lambda: connector)
    campaign_tasks.apply_action_for_account.run.__wrapped__(SimpleNamespace(), item.id)
    assert connector.delete_object.call_count == 1
    connector.update_object.assert_not_called()
    assert campaign.status == ("DELETED" if status == "SUCCESS" else "ACTIVE")
    assert item.status == ("SUCCESS" if status == "SUCCESS" else "FAILED")
    if status == "UNKNOWN":
        campaign_tasks.apply_action_for_account.run.__wrapped__(SimpleNamespace(), item.id)
        assert connector.delete_object.call_args.kwargs["confirm_only"] is True
