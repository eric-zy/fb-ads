import json

from config.settings import settings
from services.request_signer import build_signature_headers


def _signed_headers(path: str, body: bytes, *, key: str = "callback-test-secret"):
    return build_signature_headers(
        key,
        "fb_connector",
        "callback-request-1",
        "POST",
        path,
        body,
        "callback-event-1",
    )


def test_connector_media_callback_requires_valid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "SAAS_INTERNAL_SIGNING_KEY", "callback-test-secret")
    response = client.post(
        "/api/v1/internal/fb-connector/media-status",
        json={"task_id": "media-task", "media_id": "asset-1", "status": "SUCCESS", "meta_asset_id": "video-1"},
    )
    assert response.status_code == 401


def test_connector_status_callbacks_acknowledge_unknown_tasks(client, monkeypatch):
    key = "callback-test-secret"
    monkeypatch.setattr(settings, "SAAS_INTERNAL_SIGNING_KEY", key)
    cases = [
        (
            "/api/v1/internal/fb-connector/media-status",
            {"event": "media.status", "task_id": "media-task", "media_id": "asset-1", "status": "SUCCESS", "meta_asset_id": "video-1"},
        ),
        (
            "/api/v1/internal/fb-connector/delivery-status",
            {"event": "delivery.status", "task_id": "delivery-task", "status": "SUCCESS", "campaign_id": "campaign-1"},
        ),
    ]
    for path, payload in cases:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        response = client.post(path, content=body, headers=_signed_headers(path, body, key=key))
        assert response.status_code == 200
        assert response.json()["accepted"] is False
        assert response.json()["reason"] == "unknown_task"
