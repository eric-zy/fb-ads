"""Facebook Page 管理接口。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin as require_admin
from core.database import get_db
from core.enums import CredentialStatus
from core.tenant import bypass_tenant, effective_tenant_id
from models import Credential, MetaPage, User
from tasks.meta_sync_tasks import sync_meta_pages_task
from config.settings import settings
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/v1/meta-pages", tags=["Facebook Pages"])


def _query_for_user(db: Session, user: User):
    query = db.query(MetaPage)
    if user.is_platform_admin():
        # 平台管理员明确允许跨租户查看；租户管理员仍由全局 ORM 过滤隔离。
        return query
    return query


@router.get("")
def list_pages(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.is_platform_admin():
        with bypass_tenant():
            query = db.query(MetaPage)
            if status:
                query = query.filter(MetaPage.status == status)
            return [item.to_dict() for item in query.order_by(MetaPage.page_name).all()]
    query = db.query(MetaPage)
    if status:
        query = query.filter(MetaPage.status == status)
    return [item.to_dict() for item in query.order_by(MetaPage.page_name).all()]


@router.post("/sync")
def sync_pages(
    credential_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    credential = None if settings.FB_ACCESS_MODE == "connector" else db.query(Credential).filter(Credential.id == credential_id).first()
    if settings.FB_ACCESS_MODE != "connector":
        if not credential:
            raise HTTPException(status_code=404, detail="凭据不存在")
        if credential.tenant_id != effective_tenant_id(current_user):
            raise HTTPException(status_code=404, detail="凭据不存在")
        if credential.status != CredentialStatus.ACTIVE.value or credential.is_expired():
            raise HTTPException(status_code=400, detail="凭据已失效，请重新授权")
    if settings.FB_ACCESS_MODE == "connector":
        if not credential_id:
            raise HTTPException(status_code=400, detail="Connector 凭据 ID 不能为空")
        try:
            result = FBConnectorClient().sync_pages(credential_id)
            rows = result.get("pages", [])
            synced = []
            for remote in rows:
                page_id = str(remote.get("id") or "").strip()
                if not page_id:
                    continue
                page = db.query(MetaPage).filter(MetaPage.page_id == page_id).first()
                if not page:
                    page = MetaPage(id=uuid.uuid4().hex, page_id=page_id, page_name=remote.get("name") or page_id, credential_id=credential_id, tenant_id=effective_tenant_id(current_user))
                    db.add(page)
                page.page_name = remote.get("name") or page_id; page.tasks = remote.get("tasks") or []
                page.credential_id = credential_id; page.connector_credential_id = credential_id; page.status = CredentialStatus.ACTIVE.value; page.last_synced_at = datetime.utcnow()
                synced.append(page_id)
            db.commit()
            return {"task_id": None, "credential_id": credential_id, "status": "SUCCESS", "count": len(synced), "page_ids": synced}
        except FBConnectorError as exc:
            db.rollback(); raise HTTPException(status_code=503, detail=str(exc)) from exc
    task = sync_meta_pages_task.delay(credential_id)
    return {"task_id": task.id, "credential_id": credential_id, "status": "QUEUED"}
