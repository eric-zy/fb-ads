import pytest
from fastapi import HTTPException
from config.settings import settings
from models import Tenant, User, AuditLog
from api.risk_control import RiskAutomationPayload, risk_automation_state, update_risk_automation


def test_tenant_automation_control_preserves_settings_and_global_guard(db, monkeypatch):
    tenant = db.query(Tenant).filter(Tenant.id == "test_tenant").one()
    original = tenant.settings
    tenant.settings = {"timezone": "Asia/Taipei", "risk_control": {"other": "preserved"}}
    db.flush()
    admin = User(id="automation-admin", tenant_id=tenant.id, role="tenant_admin")
    monkeypatch.setattr(settings, "RISK_AUTOMATION_KILL_SWITCH", False)
    try:
        state = update_risk_automation(RiskAutomationPayload(kill_switch=True), None, admin, db)
        assert state["effective_kill_switch"] is True
        assert tenant.settings["timezone"] == "Asia/Taipei"
        assert tenant.settings["risk_control"]["other"] == "preserved"
        monkeypatch.setattr(settings, "RISK_AUTOMATION_KILL_SWITCH", True)
        state = update_risk_automation(RiskAutomationPayload(kill_switch=False), None, admin, db)
        assert state["kill_switch"] is False
        assert state["effective_kill_switch"] is True
        assert risk_automation_state(admin, db)["global_kill_switch"] is True
        assert db.query(AuditLog).filter(AuditLog.action == "UPDATE_RISK_AUTOMATION").count() == 2
        with pytest.raises(HTTPException) as exc:
            update_risk_automation(RiskAutomationPayload(kill_switch=True), None, User(id="automation-user", role="user"), db)
        assert exc.value.status_code == 403
    finally:
        tenant.settings = original
        db.commit()
