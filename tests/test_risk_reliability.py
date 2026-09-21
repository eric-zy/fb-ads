from services.fb_connector_client import FBConnectorError
from services.credential_service import CredentialError, CredentialExpiredError
from services.risk_reliability import classify_risk_error, upsert_operational_alert
from models import SyncAlert


def test_classify_risk_error_uses_operational_categories():
    assert classify_risk_error(FBConnectorError("rate", status_code=429)) == "RATE_LIMITED"
    assert classify_risk_error(FBConnectorError("auth", status_code=401)) == "CREDENTIAL_INVALID"
    assert classify_risk_error(FBConnectorError("permission", status_code=403)) == "PERMISSION_DENIED"
    assert classify_risk_error(FBConnectorError("missing", status_code=404)) == "TARGET_NOT_FOUND"
    assert classify_risk_error(FBConnectorError("upstream", status_code=503)) == "PROVIDER_UNAVAILABLE"
    assert classify_risk_error(CredentialExpiredError("expired")) == "CREDENTIAL_EXPIRED"
    assert classify_risk_error(CredentialError("missing")) == "CREDENTIAL_MISSING"


def test_operational_alert_is_deduplicated_until_resolved(db):
    first, created = upsert_operational_alert(
        db,
        tenant_id="test_tenant",
        alert_type="RISK_REDIS_UNAVAILABLE",
        title="Redis down",
        message="first",
    )
    second, created_again = upsert_operational_alert(
        db,
        tenant_id="test_tenant",
        alert_type="RISK_REDIS_UNAVAILABLE",
        title="Redis down",
        message="updated",
    )
    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert second.message == "updated"
    assert db.query(SyncAlert).filter(SyncAlert.alert_type == "RISK_REDIS_UNAVAILABLE").count() == 1
