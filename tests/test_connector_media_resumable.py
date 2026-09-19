from types import SimpleNamespace

from config.settings import settings
from fb_connector.celery_app import celery_app
from fb_connector.tasks import _upload_video_resumable


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class FakeVideoService:
    def __init__(self):
        self.transfers = []
        self.statuses = iter(["processing", "ready"])

    def start_video_upload(self, account_id, file_size):
        assert account_id == "act_123"
        assert file_size == 25
        return {
            "upload_session_id": "session-1",
            "video_id": "video-1",
            "start_offset": "0",
            "end_offset": "10",
        }

    def transfer_video_chunk(
        self, account_id, file_path, upload_session_id, start_offset, end_offset
    ):
        self.transfers.append((start_offset, end_offset))
        return {
            "start_offset": str(end_offset),
            "end_offset": str(min(end_offset + 10, 25)),
        }

    def finish_video_upload(self, account_id, upload_session_id):
        return {"success": True}

    def get_video_status(self, video_id):
        return {"status": next(self.statuses), "raw": {}}


def _row():
    return SimpleNamespace(
        task_id="task-1",
        phase="STARTING",
        status="UPLOADING",
        total_bytes=None,
        uploaded_bytes=0,
        upload_session_id=None,
        meta_video_id=None,
        start_offset=None,
        end_offset=None,
        meta_asset_id=None,
        updated_at=None,
    )


def test_resumable_video_upload_persists_offsets_and_waits_until_ready(
    tmp_path, monkeypatch
):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0123456789abcdefghijklmno")
    monkeypatch.setattr(settings, "FB_VIDEO_CHUNK_MAX_BYTES", 10)
    monkeypatch.setattr(settings, "FB_VIDEO_STATUS_POLL_INTERVAL", 0)
    monkeypatch.setattr(settings, "FB_VIDEO_PROCESSING_TIMEOUT", 5)

    row = _row()
    service = FakeVideoService()
    result = _upload_video_resumable(service, "act_123", str(path), row, FakeSession())

    assert result == {"video_id": "video-1"}
    assert service.transfers == [(0, 10), (10, 20), (20, 25)]
    assert row.phase == "READY"
    assert row.status == "SUCCESS"
    assert row.upload_session_id == "session-1"
    assert row.meta_video_id == "video-1"
    assert row.meta_asset_id == "video-1"
    assert row.uploaded_bytes == 25
    assert row.start_offset == 25
    assert row.end_offset == 25
    assert not path.exists()


def test_resumable_video_upload_resumes_from_saved_session(tmp_path, monkeypatch):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0123456789abcdefghijklmno")
    monkeypatch.setattr(settings, "FB_VIDEO_CHUNK_MAX_BYTES", 10)
    monkeypatch.setattr(settings, "FB_VIDEO_STATUS_POLL_INTERVAL", 0)
    monkeypatch.setattr(settings, "FB_VIDEO_PROCESSING_TIMEOUT", 5)

    row = _row()
    row.phase = "TRANSFERRING"
    row.total_bytes = 25
    row.uploaded_bytes = 10
    row.upload_session_id = "session-existing"
    row.meta_video_id = "video-existing"
    row.start_offset = 10
    row.end_offset = 20

    service = FakeVideoService()
    service.statuses = iter(["ready"])
    result = _upload_video_resumable(service, "act_123", str(path), row, FakeSession())

    assert result == {"video_id": "video-existing"}
    assert service.transfers == [(10, 20), (20, 25)]
    assert row.phase == "READY"
    assert row.meta_asset_id == "video-existing"


def test_processing_retry_does_not_need_local_source_file(monkeypatch):
    monkeypatch.setattr(settings, "FB_VIDEO_STATUS_POLL_INTERVAL", 0)
    monkeypatch.setattr(settings, "FB_VIDEO_PROCESSING_TIMEOUT", 5)

    row = _row()
    row.phase = "META_PROCESSING"
    row.total_bytes = 25
    row.uploaded_bytes = 25
    row.upload_session_id = "session-existing"
    row.meta_video_id = "video-existing"
    row.start_offset = 25
    row.end_offset = 25

    service = FakeVideoService()
    service.statuses = iter(["ready"])
    result = _upload_video_resumable(service, "act_123", None, row, FakeSession())

    assert result == {"video_id": "video-existing"}
    assert service.transfers == []
    assert row.phase == "READY"


def test_connector_tasks_are_isolated_by_queue():
    routes = celery_app.conf.task_routes

    assert routes["fb_connector.upload_media"]["queue"] == "connector_media"
    assert routes["fb_connector.create_campaign"]["queue"] == "connector_campaign"
    assert routes["fb_connector.fetch_insights"]["queue"] == "connector_insights"
    assert (
        routes["fb_connector.recover_stale_media_tasks"]["queue"]
        == "connector_maintenance"
    )
