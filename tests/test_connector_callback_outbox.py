from types import SimpleNamespace

import requests

from config.settings import settings
from fb_connector import models as connector_models
from fb_connector.tasks import _notify_saas_status, retry_saas_callbacks


class FakeCallbackSession:
    def __init__(self):
        self.event = None
        self.commits = 0

    def get(self, model, event_id):
        return self.event

    def add(self, event):
        self.event = event

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def test_callback_event_is_persisted_before_send(monkeypatch):
    session = FakeCallbackSession()
    monkeypatch.setattr(connector_models, "connector_session_factory", lambda: session)
    monkeypatch.setattr(settings, "SAAS_CALLBACK_BASE_URL", "https://saas.example.com")
    monkeypatch.setattr(settings, "SAAS_INTERNAL_SIGNING_KEY", "callback-secret")

    sent = []

    def fake_post(url, **kwargs):
        sent.append((url, kwargs))
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None)

    monkeypatch.setattr("fb_connector.tasks.requests.post", fake_post)
    result = _notify_saas_status(
        "/api/v1/internal/fb-connector/media-status",
        {"event": "media.status", "task_id": "task-1", "status": "SUCCESS"},
        "media-binding-1",
    )

    assert result is True
    assert session.event.status == "SENT"
    assert session.event.attempt_count == 1
    assert sent[0][0].endswith("/api/v1/internal/fb-connector/media-status")


def test_callback_event_failure_is_scheduled_for_retry(monkeypatch):
    session = FakeCallbackSession()
    monkeypatch.setattr(connector_models, "connector_session_factory", lambda: session)
    monkeypatch.setattr(settings, "SAAS_CALLBACK_BASE_URL", "https://saas.example.com")
    monkeypatch.setattr(settings, "SAAS_INTERNAL_SIGNING_KEY", "callback-secret")

    def fake_post(*args, **kwargs):
        raise requests.Timeout("callback timeout")

    monkeypatch.setattr("fb_connector.tasks.requests.post", fake_post)
    result = _notify_saas_status(
        "/api/v1/internal/fb-connector/delivery-status",
        {"event": "delivery.status", "task_id": "task-2", "status": "FAILED"},
        "deploy-task-2",
    )

    assert result is False
    assert session.event.status == "RETRY"
    assert session.event.attempt_count == 1
    assert session.event.next_retry_at is not None
