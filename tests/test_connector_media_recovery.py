from datetime import datetime, timedelta
from types import SimpleNamespace

from fb_connector.api.media import _media_task_is_stale
from fb_connector.api.campaigns import _cleanup_object_ids, _delivery_task_is_stale
from config.settings import settings


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


def test_media_poll_window_covers_video_upload_timeout():
    assert settings.CONNECTOR_MEDIA_POLL_MAX_RETRIES * 15 >= settings.FB_VIDEO_UPLOAD_TIMEOUT


def test_delivery_poll_window_covers_domestic_recovery_threshold():
    assert (
        settings.FB_CONNECTOR_DELIVERY_POLL_MAX_RETRIES * 15
        >= settings.ASYNC_TASK_STALE_SECONDS
    )


def test_cleanup_excludes_reused_objects_and_can_target_orphans_only():
    row = SimpleNamespace(
        campaign_id="campaign-new",
        request_payload={"campaign": {"existing_id": "campaign-reused"}},
        objects={
            "adsets": [
                {"id": "adset-reused", "reused": True},
                {"id": "adset-new"},
            ],
            "creatives": [{"id": "creative-new"}],
            "ads": [{"id": "ad-new"}],
            "orphaned": [{"id": "creative-old"}, {"id": "ad-old"}],
        },
    )

    assert _cleanup_object_ids(row) == [
        "ad-new",
        "creative-new",
        "adset-new",
        "creative-old",
        "ad-old",
    ]
    assert _cleanup_object_ids(row, orphaned_only=True) == ["creative-old", "ad-old"]
