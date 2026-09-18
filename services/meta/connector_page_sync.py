"""Persist Facebook Pages returned by the overseas Connector."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from core.enums import CredentialStatus
from models import MetaPage
from services.fb_connector_client import FBConnectorClient


def sync_connector_pages(db: Session, tenant_id: str, credential_id: str) -> dict:
    """Synchronize one Connector credential's Pages into the SaaS database.

    The Connector remains the owner of Page access tokens.  SaaS stores only
    the selectable Page metadata and the opaque Connector credential ID.
    """
    result = FBConnectorClient().sync_pages(credential_id)
    rows = result.get("pages", [])
    seen: set[str] = set()
    synced: list[str] = []

    for remote in rows:
        page_id = str(remote.get("id") or "").strip()
        if not page_id:
            continue
        seen.add(page_id)
        page = (
            db.query(MetaPage)
            .filter(MetaPage.tenant_id == tenant_id, MetaPage.page_id == page_id)
            .first()
        )
        if not page:
            page = MetaPage(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                page_id=page_id,
                page_name=remote.get("name") or page_id,
                credential_id=credential_id,
            )
            db.add(page)

        page.page_name = remote.get("name") or page_id
        page.category = remote.get("category")
        page.tasks = remote.get("tasks") or []
        page.credential_id = credential_id
        page.connector_credential_id = credential_id
        page.status = CredentialStatus.ACTIVE.value
        page.last_error = None
        page.last_synced_at = datetime.utcnow()
        synced.append(page_id)

    # Mark Pages no longer returned by Meta as unavailable for selection while
    # retaining the record for audit/history.
    existing = (
        db.query(MetaPage)
        .filter(
            MetaPage.tenant_id == tenant_id,
            MetaPage.connector_credential_id == credential_id,
        )
        .all()
    )
    for page in existing:
        if page.page_id not in seen:
            page.status = CredentialStatus.DISABLED.value
            page.last_error = "页面已不在当前 Meta 授权范围内"

    return {"credential_id": credential_id, "count": len(synced), "page_ids": synced}
