from datetime import datetime, timedelta
from types import SimpleNamespace

from fb_connector.api.media import _media_task_is_stale
from fb_connector.api.campaigns import _delivery_task_is_stale


def test_media_task_is_stale_only_for_active_states(monkeypatch):
    monkeypatch.setattr("fb_connector.api.media.settings.CONNECTOR_MEDIA_STALE_SECONDS", 60)
    now = datetime.utcnow()
    old = now - timedelta(seconds=61)

    assert _media_task_is_stale(SimpleNamespace(status="UPLOADING", updated_at=old), now)
    assert _media_task_is_stale(SimpleNamespace(status="RETRY", updated_at=old), now)
    assert not _media_task_is_stale(SimpleNamespace(status="SUCCESS", updated_at=old), now)
    assert not _media_task_is_stale(SimpleNamespace(status="UPLOADING", updated_at=now), now)


def test_delivery_task_recovery_uses_same_stale_boundary(monkeypatch):
    monkeypatch.setattr("fb_connector.api.campaigns.settings.CONNECTOR_MEDIA_STALE_SECONDS", 60)
    now = datetime.utcnow()
    old = now - timedelta(seconds=61)

    assert _delivery_task_is_stale(SimpleNamespace(status="RUNNING", updated_at=old), now)
    assert _delivery_task_is_stale(SimpleNamespace(status="RETRY", updated_at=old), now)
    assert _delivery_task_is_stale(SimpleNamespace(status="QUEUED", updated_at=old), now)
    assert not _delivery_task_is_stale(SimpleNamespace(status="SUCCESS", updated_at=old), now)
