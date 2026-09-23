from types import SimpleNamespace


def test_task_status_exposes_only_safe_single_ad_group_refresh_fields(monkeypatch, db):
    import api.campaigns as campaigns
    from models import AsyncTaskRecord, User

    user = User(
        id="sync-status-user",
        email="sync-status@example.com",
        username="sync-status",
        hashed_password="test",
        tenant_id="test_tenant",
    )
    db.add(user)
    db.add(AsyncTaskRecord(
        task_id="abcdef12-3456-7890-abcd-ef1234567890",
        task_type="META_SYNC",
        object_type="ADSET",
        object_ids=["group-1"],
        created_by=user.id,
    ))
    db.commit()

    class FakeResult:
        state = "SUCCESS"

        def successful(self):
            return True

        def failed(self):
            return False

        def ready(self):
            return True

        result = {
            "status": "success",
            "ad_group_id": "group-1",
            "updated_at": "2026-09-23T10:00:00",
            "account_id": "account-secret-not-needed",
            "remote_payload": {"token": "must-not-leak"},
        }

    monkeypatch.setattr(campaigns.celery_app, "AsyncResult", lambda task_id: FakeResult())
    monkeypatch.setattr(campaigns, "_scope", lambda query, model, current_user: query)
    monkeypatch.setattr(campaigns, "_visible_accounts", lambda db, user: None)

    result = campaigns.get_async_task_status(
        "abcdef12-3456-7890-abcd-ef1234567890",
        db=db,
        current_user=user,
    )
    assert result["result"] == {
        "status": "success",
        "error_count": 0,
        "ad_group_id": "group-1",
        "updated_at": "2026-09-23T10:00:00",
    }
    assert "remote_payload" not in result["result"]
