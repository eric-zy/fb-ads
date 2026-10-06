import asyncio
import json
from fastapi import HTTPException, Request
import pytest
from config.settings import settings
from core.tenant import tenant_scope
from models import AdAccount, AccountInsight, MetaAccount
from api.connector_callbacks_insights import insights_callback
from services.request_signer import build_signature_headers


@pytest.mark.parametrize("ambiguous", [False, True])
def test_callback_matches_credential_and_rejects_ambiguous_local_owners(db, monkeypatch, ambiguous):
    monkeypatch.setattr(settings, "SAAS_INTERNAL_SIGNING_KEY", "mapping-test-key")
    for index, tenant in enumerate(("test_tenant", "other-mapping-tenant")):
        with tenant_scope(tenant):
            business = MetaAccount(id=f"mapping-bm-{index}", name="Mapping", business_id=f"remote-mapping-{index}",
                                   connector_credential_id="same-credential" if ambiguous else f"credential-{index}")
            db.add(business)
            db.add(AdAccount(id=f"mapping-account-{index}", account_id="act_mapping_duplicate", business_id=business.id))
            db.flush()
    body = json.dumps({"request_id": "mapping-request", "credential_id": "same-credential" if ambiguous else "credential-1",
                       "account_id": "act_mapping_duplicate", "days": 1,
                       "items": [{"date_start": "2026-10-06", "spend": "10"}]}).encode()
    path = "/api/v1/internal/fb-connector/insights"
    headers = build_signature_headers("mapping-test-key", "fb_connector", "mapping-request", "POST", path, body, "mapping-request")
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": path}, receive=receive)
    def call():
        return asyncio.run(insights_callback(request, db, headers["X-Signature"], headers["X-Timestamp"],
                                             headers["X-Request-Id"], headers["X-Idempotency-Key"]))
    if ambiguous:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 409
    else:
        assert call()["canonical_count"] == 1
        with tenant_scope("other-mapping-tenant"):
            row = db.query(AccountInsight).one()
            assert row.ad_account_id == "mapping-account-1"
        with tenant_scope("test_tenant"):
            assert db.query(AccountInsight).count() == 0
