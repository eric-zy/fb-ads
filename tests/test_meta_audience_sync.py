from types import SimpleNamespace

from models import AdAccount, AsyncTaskRecord, MetaAudienceAsset, User
from services.meta_audience_service import MetaAudienceSyncService


def test_custom_audience_sync_upserts_metadata_without_clearing_required_flag(db, monkeypatch):
    account = AdAccount(id="aud-account", account_id="act_aud", connector_credential_id="conn-1")
    db.add(account)
    db.commit()

    monkeypatch.setattr("services.meta_audience_service.settings.FB_ACCESS_MODE", "connector")
    responses = [
        {"data": [{"id": "aud-1", "name": "旧客户", "subtype": "CUSTOM", "delivery_status": "READY"}]},
        {"data": [{"id": "aud-1", "name": "更新后的客户", "subtype": "CUSTOM", "sharing_status": "ACTIVE"}]},
    ]

    class FakeConnector:
        def list_custom_audiences(self, account_id, credential_id):
            return responses.pop(0)

    monkeypatch.setattr("services.meta_audience_service.FBConnectorClient", FakeConnector)

    first = MetaAudienceSyncService(db).sync_account(account.id)
    assert first["status"] == "SUCCESS"
    assert first["count"] == 1

    row = db.query(MetaAudienceAsset).filter(MetaAudienceAsset.meta_audience_id == "aud-1").one()
    row.is_required_exclusion = True
    db.commit()

    second = MetaAudienceSyncService(db).sync_account(account.id)

    assert second["count"] == 1
    db.refresh(row)
    assert row.name == "更新后的客户"
    assert row.sharing_status == "ACTIVE"
    assert row.is_required_exclusion is True


def test_sync_endpoint_returns_existing_active_task(monkeypatch, db):
    import api.meta_audiences as meta_audiences

    account = AdAccount(id="queued-account", account_id="act_queued", connector_credential_id="conn-1")
    user = User(
        id="queued-user",
        email="queued@example.com",
        username="queued",
        hashed_password="test",
        tenant_id="test_tenant",
    )
    db.add_all([account, user])
    db.flush()
    db.add(
        AsyncTaskRecord(
            task_id="existing-task",
            task_type="META_CUSTOM_AUDIENCE_SYNC",
            object_type="CUSTOM_AUDIENCE",
            object_ids=[account.id],
            status="STARTED",
            created_by=user.id,
        )
    )
    db.commit()

    monkeypatch.setattr(meta_audiences, "can_access_account", lambda db, user, account_id: True)
    monkeypatch.setattr(
        meta_audiences.sync_custom_audiences_task,
        "delay",
        lambda account_pk: (_ for _ in ()).throw(AssertionError("不应重复入队")),
    )

    result = meta_audiences.sync_audiences(
        account.id,
        request=SimpleNamespace(),
        db=db,
        current_user=user,
    )

    assert result == {
        "status": "ALREADY_QUEUED",
        "task_id": "existing-task",
        "account_pk": account.id,
        "account_id": account.account_id,
    }
