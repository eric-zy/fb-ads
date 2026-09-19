"""Persist Facebook Pages returned by the overseas Connector."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from core.enums import CredentialStatus
from models import MetaPage
from services.fb_connector_client import FBConnectorClient


def sync_connector_pages(
    db: Session,
    tenant_id: str,
    credential_id: str,
    *,
    allow_rebind: bool = False,
) -> dict:
    """Synchronize one Connector credential's Pages into the SaaS database.

    The Connector remains the owner of Page access tokens.  SaaS stores only
    the selectable Page metadata and the opaque Connector credential ID.

    Automatic/bulk synchronization must not silently move a Page from one
    authorization to another.  Explicit synchronization after a user chooses
    a credential may opt into rebinding.
    """
    result = FBConnectorClient().sync_pages(credential_id)
    rows = result.get("pages", [])
    seen: set[str] = set()
    synced: list[str] = []
    conflicts: list[dict] = []

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
        elif not allow_rebind and (
            page.connection_id is not None
            or page.connector_credential_id not in (None, credential_id)
        ):
            conflicts.append({
                "page_id": page_id,
                "existing_credential_id": page.connector_credential_id,
                "requested_credential_id": credential_id,
                "reason": "页面已绑定其他授权，未自动覆盖",
            })
            continue

        page.page_name = remote.get("name") or page_id
        page.category = remote.get("category")
        page.tasks = remote.get("tasks") or []
        page.credential_id = credential_id
        page.connector_credential_id = credential_id
        # Connector 授权不使用本地 OAuth connection，重绑时清理旧连接，
        # 避免后续自动同步把已重绑的 Page 再识别为冲突。
        page.connection_id = None
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

    return {
        "credential_id": credential_id,
        "count": len(synced),
        "page_ids": synced,
        "conflicts": conflicts,
    }
