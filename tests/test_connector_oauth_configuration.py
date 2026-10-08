import asyncio
import json
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from config.settings import settings
from fb_connector.api import oauth


@pytest.fixture
def configured_connector(monkeypatch):
    values = {
        "FB_APP_ID": "test-app",
        "FB_APP_SECRET": "test-app-secret",
        "FB_OAUTH_REDIRECT_URI": "https://iornix.com/internal/meta/oauth/callback",
        "FB_CONNECTOR_SIGNING_KEY": "test-shared-oauth-signing-key",
        "SAAS_INTERNAL_SIGNING_KEY": "test-shared-callback-key",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    return values


@pytest.mark.parametrize("value", ["", "   "])
def test_missing_signing_key_is_rejected_without_secret_values(configured_connector, monkeypatch, value):
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", value)
    assert settings.missing_connector_config() == ["FB_CONNECTOR_SIGNING_KEY"]
    with pytest.raises(ValueError, match="FB_CONNECTOR_SIGNING_KEY") as error:
        settings.validate_connector_config()
    assert "test-app-secret" not in str(error.value)


def test_configured_connector_passes_preflight(configured_connector):
    assert settings.missing_connector_config() == []
    settings.validate_connector_config()


def test_runtime_validation_includes_oauth_signing_key(configured_connector, monkeypatch):
    monkeypatch.setattr(settings, "APP_ROLE", "fb_connector")
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "")
    with pytest.raises(ValueError, match="FB_CONNECTOR_SIGNING_KEY"):
        settings.validate_runtime_config()


def test_authorization_fails_before_opening_meta_if_signing_is_missing(configured_connector, monkeypatch):
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "")
    service = Mock(side_effect=AssertionError("Must not start Meta OAuth"))
    monkeypatch.setattr(oauth, "MetaOAuthService", service)
    with pytest.raises(HTTPException) as error:
        asyncio.run(oauth.authorize(oauth.AuthorizeRequest(state="unused")))
    assert error.value.status_code == 503
    assert "deploy/fb-connector.env" in error.value.detail
    assert "FB_CONNECTOR_SIGNING_KEY" in error.value.detail
    service.assert_not_called()


def test_callback_fails_before_token_exchange_if_signing_is_missing(configured_connector, monkeypatch):
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "")
    exchange = Mock(side_effect=AssertionError("Must not exchange an authorization code"))
    monkeypatch.setattr(oauth, "exchange", exchange)
    monkeypatch.setenv("SAAS_CALLBACK_BASE_URL", "http://49.232.238.163:8094")
    response = asyncio.run(oauth.callback(state="unused", code="unused", error=None, error_description=None))
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["meta_auth"] == ["error"]
    assert "FB_CONNECTOR_SIGNING_KEY" in query["message"][0]
    assert "credential_id" not in query and "receipt" not in query
    exchange.assert_not_called()


def test_missing_signing_key_blocks_readiness_before_dependency_checks(configured_connector, monkeypatch):
    from fb_connector.main import ready
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "")
    response = ready()
    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "not_ready", "missing": ["FB_CONNECTOR_SIGNING_KEY"]}


def test_valid_config_still_requires_dependencies_for_readiness(configured_connector, monkeypatch):
    from fb_connector.main import ready
    monkeypatch.setattr("services.readiness.dependency_readiness", lambda *args: {
        "status": "not_ready", "checks": {"database": "ok", "redis": "unavailable"}})
    assert ready().status_code == 503
    monkeypatch.setattr("services.readiness.dependency_readiness", lambda *args: {
        "status": "ready", "checks": {"database": "ok", "redis": "ok"}})
    response = ready()
    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "ready"

@pytest.mark.parametrize("configured", [True, False])
def test_protected_version_probe_reports_presence_without_exposing_secret(configured_connector, monkeypatch, configured):
    from fb_connector.main import meta_version
    monkeypatch.setattr(settings, "FB_CONNECTOR_SIGNING_KEY", "test-private-signing-value" if configured else "")
    result = asyncio.run(meta_version(None))
    assert result["oauth_receipt_signing_configured"] is configured
    assert result["oauth_callback_contract"] == "signed_receipt_v1"
    assert "test-private-signing-value" not in json.dumps(result)
