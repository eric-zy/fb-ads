from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.tenant import tenant_scope
from fb_connector.models import ConnectorCredential
from fb_connector.credential_store import DatabaseCredentialVault, _cipher
from models import AdAccount
from services.connector_health import connector_health_rows
from services.fb_connector_client import FBConnectorError


@pytest.mark.parametrize("days,scopes,expected", [
    (30, ["ads_read", "ads_management"], "ACTIVE"),
    (2, ["ads_read", "ads_management"], "EXPIRING"),
    (-1, ["ads_read", "ads_management"], "EXPIRED"),
    (30, ["ads_read"], "PERMISSION_MISSING"),
])
def test_vault_health_and_expired_token_rejection(monkeypatch, days, scopes, expected):
    engine = create_engine("sqlite://")
    ConnectorCredential.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(ConnectorCredential(id="known", app_id="app", scopes=scopes,
                    access_token_encrypted=_cipher().encrypt(b"private-token").decode(),
                    expires_at=datetime.utcnow() + timedelta(days=days)))
        session.commit()
    monkeypatch.setattr("fb_connector.credential_store.connector_session_factory", factory)
    vault = DatabaseCredentialVault()
    result = vault.health(["known", "missing"])
    assert result[0]["health"] == expected
    assert result[1]["health"] == "MISSING"
    assert "private-token" not in str(result)
    assert "access_token_encrypted" not in str(result)
    if expected == "EXPIRED":
        with pytest.raises(KeyError):
            vault.get_access_token("known")
    else:
        assert vault.get_access_token("known") == "private-token"
    engine.dispose()


def test_domestic_health_only_requests_current_tenant_references(db, monkeypatch):
    for tenant in ("test_tenant", "other-health-tenant"):
        with tenant_scope(tenant):
            db.add(AdAccount(id=tenant + "-health", account_id="act_" + tenant,
                            connector_credential_id=tenant + "-credential"))
            db.flush()
    client = Mock()
    client.credential_health.return_value = {"items": [{"id": "test_tenant-credential", "health": "ACTIVE", "access_token": "must-be-removed"},
                                                       {"id": "unrequested", "health": "ACTIVE"}]}
    monkeypatch.setattr("services.connector_health.FBConnectorClient", lambda: client)
    result = connector_health_rows(db)
    client.credential_health.assert_called_once_with(["test_tenant-credential"])
    assert len(result) == 1
    assert result[0]["account_ids"] == ["test_tenant-health"]
    assert "must-be-removed" not in str(result)
    client.credential_health.side_effect = FBConnectorError("private upstream error")
    result = connector_health_rows(db)
    assert result[0]["health"] == "UNAVAILABLE"
    assert "private upstream error" not in str(result)
