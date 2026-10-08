"""Page refresh must preserve independent personal authorizations."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from api import meta_pages
from models import MetaConnection, MetaConnectionAsset, MetaPage, User
from services.meta.connector_page_sync import sync_connector_pages


def personal_page(db):
    user = User(id="page-owner", username="page-owner", email="page-owner@test.local",
                hashed_password="unused", role="user", is_active=True)
    connection = MetaConnection(id="page-connection", meta_user_id="page-subject", app_id="page-app",
        authorized_by_user_id=user.id, access_mode="connector", credential_id="current-credential",
        status="ACTIVE", scopes=["ads_management", "ads_read"], expires_at=datetime.utcnow() + timedelta(days=30))
    page = MetaPage(id="shared-page", page_id="101", page_name="Shared Page", status="ACTIVE",
        credential_id="old-credential", connector_credential_id="old-credential")
    grant = MetaConnectionAsset(id="personal-page-grant", connection_id=connection.id,
        asset_type="PAGE", asset_id=page.id, status="ACTIVE", tasks=["ADVERTISE"])
    db.add_all([user, connection, page, grant])
    db.flush()
    return user, connection, page, grant


def test_old_credential_refresh_does_not_hide_an_independently_authorized_page(db, monkeypatch):
    user, connection, page, grant = personal_page(db)
    monkeypatch.setattr("services.meta.connector_page_sync.FBConnectorClient",
        lambda: SimpleNamespace(sync_pages=lambda _: {"pages": []}))
    sync_connector_pages(db, "test_tenant", "old-credential")
    db.flush()
    assert page.status == "ACTIVE"
    assert grant.status == "ACTIVE"
    assert [p["page_id"] for p in meta_pages.list_pages("ACTIVE", db, user)] == ["101"]
    unrelated = User(id="unrelated-publisher", role="user")
    assert meta_pages.list_pages("ACTIVE", db, unrelated) == []


def test_old_credential_refresh_still_disables_pages_without_other_access(db, monkeypatch):
    _, connection, page, grant = personal_page(db)
    grant.status = "REVOKED"
    db.flush()
    monkeypatch.setattr("services.meta.connector_page_sync.FBConnectorClient",
        lambda: SimpleNamespace(sync_pages=lambda _: {"pages": []}))
    sync_connector_pages(db, "test_tenant", "old-credential")
    assert page.status == "DISABLED"


def test_bulk_page_refresh_includes_personal_credentials_without_canonical_bindings(db, monkeypatch):
    _, connection, page, _ = personal_page(db)
    page.connector_credential_id = None
    admin = User(id="page-admin", username="page-admin", email="page-admin@test.local",
                 hashed_password="unused", role="tenant_admin", is_active=True)
    db.add(admin)
    db.flush()
    calls = []
    def refresh(session, tenant, credential):
        calls.append((tenant, credential))
        return {"count": 1, "page_ids": ["101"], "conflicts": []}
    monkeypatch.setattr(meta_pages, "sync_connector_pages", refresh)
    monkeypatch.setattr(db, "commit", db.flush)
    result = meta_pages.sync_all_pages(db, admin)
    assert calls == [("test_tenant", connection.credential_id)]
    assert result["count"] == 1
