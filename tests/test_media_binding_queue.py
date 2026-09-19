from types import SimpleNamespace

from services.media_binding_service import queue_pending_asset_bindings


class FakeDB:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount
        self.commits = 0

    def execute(self, statement):
        return SimpleNamespace(rowcount=self.rowcount)

    def commit(self):
        self.commits += 1


def test_queue_pending_bindings_claims_before_enqueue(monkeypatch):
    import tasks.media_tasks as media_tasks

    calls = []

    class FakeTask:
        @staticmethod
        def delay(binding_id):
            calls.append(binding_id)
            return SimpleNamespace(id="celery-task-1")

    monkeypatch.setattr(media_tasks, "upload_asset_task", FakeTask)
    binding = SimpleNamespace(
        id="binding-1",
        status="PENDING",
        meta_asset_id=None,
        processing_status=None,
        error_message="old",
        error_code="old",
    )
    db = FakeDB()

    queued = queue_pending_asset_bindings([binding], db=db)

    assert queued == [{"binding_id": "binding-1", "task_id": "celery-task-1"}]
    assert calls == ["binding-1"]
    assert binding.status == "PROCESSING"
    assert binding.processing_status == "QUEUED"
    assert db.commits == 1


def test_queue_pending_bindings_skips_claimed_binding():
    binding = SimpleNamespace(
        id="binding-1",
        status="PENDING",
        meta_asset_id=None,
        processing_status=None,
        error_message=None,
        error_code=None,
    )

    queued = queue_pending_asset_bindings([binding], db=FakeDB(rowcount=0))

    assert queued == []
    assert binding.status == "PENDING"
