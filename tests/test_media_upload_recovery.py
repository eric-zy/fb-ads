from types import SimpleNamespace

from tasks.recovery_tasks import _mark_upload_completed


class FakeDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class FakeStorage:
    def __init__(self, parts, size):
        self.parts = parts
        self.size = size
        self.completed = 0

    def list_multipart_parts(self, key, upload_id):
        return self.parts

    def complete_multipart_upload(self, key, upload_id, parts):
        self.completed += 1

    def head(self, key):
        return SimpleNamespace(size=self.size)


def _session():
    return SimpleNamespace(
        id="session-1",
        asset_id="asset-1",
        object_key="tenant/asset/video.mp4",
        upload_mode="multipart",
        upload_id="upload-1",
        part_count=2,
        expected_size=10,
        status="UPLOADING",
        completed_at=None,
        error_message="old error",
    )


def test_recovery_completes_full_multipart_upload(monkeypatch):
    monkeypatch.setattr("tasks.media_tasks.process_oss_asset_task.delay", lambda asset_id: None)
    db = FakeDb()
    session = _session()
    asset = SimpleNamespace(
        id="asset-1",
        storage_status="UPLOADING",
        processing_status="PENDING",
        status="PENDING",
        error="old error",
    )
    storage = FakeStorage(
        [{"part_number": 1, "etag": "etag-1"}, {"part_number": 2, "etag": "etag-2"}],
        10,
    )
    result = {"upload_sessions_recovered": 0}

    assert _mark_upload_completed(db, session, asset, storage=storage, result=result)
    assert storage.completed == 1
    assert session.status == "COMPLETED"
    assert asset.storage_status == "READY"
    assert asset.processing_status == "PROCESSING"
    assert result["upload_sessions_recovered"] == 1
    assert db.commits == 1


def test_recovery_defers_when_a_multipart_part_is_missing():
    db = FakeDb()
    session = _session()
    asset = SimpleNamespace(storage_status="UPLOADING", processing_status="PENDING", status="PENDING")
    storage = FakeStorage([{"part_number": 1, "etag": "etag-1"}], 10)
    result = {"upload_sessions_recovered": 0}

    assert not _mark_upload_completed(db, session, asset, storage=storage, result=result)
    assert session.status == "UPLOADING"
    assert storage.completed == 0
    assert db.commits == 0


def test_recovery_defers_when_object_size_does_not_match():
    db = FakeDb()
    session = _session()
    asset = SimpleNamespace(storage_status="UPLOADING", processing_status="PENDING", status="PENDING")
    storage = FakeStorage(
        [{"part_number": 1, "etag": "etag-1"}, {"part_number": 2, "etag": "etag-2"}],
        9,
    )
    result = {"upload_sessions_recovered": 0}

    assert not _mark_upload_completed(db, session, asset, storage=storage, result=result)
    assert session.status == "UPLOADING"
    assert storage.completed == 1
    assert db.commits == 0
