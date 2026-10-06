from celery import Celery
from celery.contrib.testing.worker import start_worker

from scripts import check_celery_worker


def test_probe_completes_an_actual_in_memory_worker_task(monkeypatch, capsys):
    app = Celery("worker_probe_test", broker="memory://", backend="cache+memory://")

    @app.task(name="celery_app.debug_task")
    def harmless_task():
        return None

    monkeypatch.setattr(check_celery_worker, "celery_app", app)
    with start_worker(app, pool="solo", concurrency=1, perform_ping_check=False, loglevel="ERROR"):
        assert check_celery_worker.main() == 0
    assert "PASS" in capsys.readouterr().out


def test_probe_failure_does_not_expose_broker_error(monkeypatch, capsys):
    class BrokenApp:
        def send_task(self, *_args, **_kwargs):
            raise ConnectionError("redis://user:secret@private-host")

    monkeypatch.setattr(check_celery_worker, "celery_app", BrokenApp())
    assert check_celery_worker.main() == 1
    output = capsys.readouterr().out
    assert "FAIL" in output
    assert "secret" not in output
