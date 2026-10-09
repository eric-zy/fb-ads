"""Operations probes must degrade safely and verify the authenticated channel."""
from types import SimpleNamespace

import pytest
import requests

from api.operations import system_health
from config.settings import settings
from core.auth import AuthManager, get_current_active_user
from main import app
from services.request_signer import verify_request


READY = {"status": "ready", "service": "fb_connector", "checks": {
    "database": "ok", "redis": "ok", "oauth_receipt_signing": "ok",
}}
VERSION = {"service": "fb_connector", "oauth_callback_contract": "signed_receipt_v1",
           "oauth_receipt_signing_configured": True}


def response(payload, status=200):
    return SimpleNamespace(status_code=status, content=b"json", headers={}, json=lambda: payload)


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setattr("services.readiness.dependency_readiness", lambda *_: {
        "status": "ready", "checks": {"database": "ok", "redis": "ok"},
    })
    monkeypatch.setattr("celery_app.celery_app.control.inspect", lambda **_: SimpleNamespace(
        ping=lambda: {"worker-test": {"ok": "pong"}},
    ))
    monkeypatch.setattr(settings, "FB_ACCESS_MODE", "connector")
    monkeypatch.setattr(settings, "FB_CONNECTOR_ENABLED", True)
    monkeypatch.setattr(settings, "FB_CONNECTOR_BASE_URL", "https://connector.test")
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "probe-test-key")
    monkeypatch.setattr(settings, "CONNECTOR_SERVICE_TOKEN", "probe-test-token")
    monkeypatch.setattr(settings, "FB_CONNECTOR_TIMEOUT", 30)
    monkeypatch.setattr("api.operations.requests.get", lambda *_a, **_kw: response(READY))
    monkeypatch.setattr("services.fb_connector_client.requests.request", lambda *_a, **_kw: response(VERSION))


@pytest.mark.parametrize("payload", [
    None, [], "ready", {"status": "ready"},
    {"status": "ready", "checks": []}, {"status": "ready", "checks": "invalid"},
    {**READY, "checks": {**READY["checks"], "database": "unavailable"}},
    {**READY, "checks": {"database": "ok", "redis": "ok"}},
    {**READY, "checks": {**READY["checks"], "redis": ["ok"]}},
    {**READY, "service": "other"},
])
def test_malformed_or_inconsistent_readiness_degrades(probes, monkeypatch, payload):
    monkeypatch.setattr("api.operations.requests.get", lambda *_a, **_kw: response(payload))
    result = system_health(None)
    assert result["status"] == "degraded"
    assert result["checks"]["connector"] == "unavailable"
    assert all(value in {"ok", "unavailable"} for value in result["connector"]["checks"].values())


def test_signed_probe_uses_business_credentials_and_bounded_timeout(probes, monkeypatch):
    captured = {}

    def signed_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return response(VERSION)

    monkeypatch.setattr("services.fb_connector_client.requests.request", signed_request)
    result = system_health(None)
    assert result["status"] == "ready"
    assert result["connector"]["checks"]["service_auth"] == "ok"
    assert captured["method"] == "GET"
    assert captured["url"] == "https://connector.test/internal/meta/version"
    assert captured["timeout"] == 5.0
    assert captured["headers"]["Authorization"] == "Bearer probe-test-token"
    assert verify_request("probe-test-key", captured["headers"], "GET", "/internal/meta/version", captured["data"])


@pytest.mark.parametrize("payload,status", [(VERSION, 401), (None, 200), ([], 200),
    ({**VERSION, "service": "other"}, 200), ({**VERSION, "oauth_receipt_signing_configured": False}, 200)])
def test_public_ready_cannot_mask_authentication_failure(probes, monkeypatch, payload, status):
    monkeypatch.setattr("services.fb_connector_client.requests.request", lambda *_a, **_kw: response(payload, status))
    result = system_health(None)
    assert result["status"] == "degraded"
    assert result["connector"]["checks"]["database"] == "ok"
    assert result["connector"]["checks"]["service_auth"] == "unavailable"


@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), ValueError("invalid json")])
def test_ready_errors_are_safe(probes, monkeypatch, failure):
    def unavailable(*_a, **_kw):
        raise failure
    monkeypatch.setattr("api.operations.requests.get", unavailable)
    assert system_health(None)["status"] == "degraded"


def test_sensitive_remote_fields_are_not_exposed(probes, monkeypatch):
    payload = {**READY, "missing": ["SECRET"], "token": "private", "checks": {**READY["checks"], "secret": "private"}}
    monkeypatch.setattr("api.operations.requests.get", lambda *_a, **_kw: response(payload))
    result = system_health(None)
    assert result["status"] == "ready"
    assert "private" not in str(result) and "SECRET" not in str(result)


def test_direct_mode_skips_connector_network(probes, monkeypatch):
    monkeypatch.setattr(settings, "FB_ACCESS_MODE", "direct")
    def unexpected(*_a, **_kw):
        pytest.fail("Direct mode must not contact Connector")
    monkeypatch.setattr("api.operations.requests.get", unexpected)
    monkeypatch.setattr("services.fb_connector_client.requests.request", unexpected)
    result = system_health(None)
    assert result["status"] == "ready"
    assert result["connector"]["status"] == "not_required"


@pytest.mark.parametrize("role,status", [("user", 403), ("tenant_admin", 200), ("platform_admin", 200)])
def test_health_requires_admin(client, probes, role, status):
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role)
    try:
        token = AuthManager.create_access_token({"sub": "probe-user", "tenant_id": "test_tenant"})
        assert client.get("/api/v1/operations/health", headers={"Authorization": f"Bearer {token}"}).status_code == status
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)
