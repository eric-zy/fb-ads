"""XMP 风格的 Meta 授权连接管理接口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.auth import require_meta_asset_admin as require_admin
from core.database import get_db
from core.tenant import bypass_tenant
from config.settings import settings
from models import AdAccount, Credential, MetaAccount, MetaConnection, MetaPage, User
from tasks.meta_sync_tasks import sync_meta_authorization_task

router = APIRouter(prefix="/api/v1/meta-connections", tags=["Meta 授权连接"])


def _rows(db: Session):
    query = db.query(MetaConnection)
    result = []
    for connection in query.order_by(MetaConnection.updated_at.desc()).all():
        item = connection.to_dict()
        item["business_count"] = db.query(func.count(MetaAccount.id)).filter(
            MetaAccount.connection_id == connection.id
        ).scalar() or 0
        item["account_count"] = db.query(func.count(AdAccount.id)).filter(
            AdAccount.connection_id == connection.id
        ).scalar() or 0
        item["page_count"] = db.query(func.count(MetaPage.id)).filter(
            MetaPage.connection_id == connection.id,
            MetaPage.status == "ACTIVE",
        ).scalar() or 0
        item["credential_count"] = db.query(func.count(Credential.id)).filter(
            Credential.connection_id == connection.id,
            Credential.status == "ACTIVE",
        ).scalar() or 0
        result.append(item)
    return result


@router.get("")
def list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if settings.FB_ACCESS_MODE == "connector":
        return []
    if current_user.is_platform_admin():
        with bypass_tenant():
            return _rows(db)
    return _rows(db)


@router.post("/{connection_id}/sync")
def sync_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if settings.FB_ACCESS_MODE == "connector":
        raise HTTPException(status_code=410, detail="当前使用海外 Connector OAuth，请通过 BM 页面同步")
    connection = db.query(MetaConnection).filter(MetaConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(status_code=404, detail="Meta 授权连接不存在")
    credentials = db.query(Credential).filter(
        Credential.connection_id == connection_id,
        Credential.status == "ACTIVE",
    ).order_by(Credential.updated_at.desc()).all()
    if not credentials:
        raise HTTPException(status_code=400, detail="该授权连接没有有效凭据，请重新授权")
    task_ids = [sync_meta_authorization_task.delay(row.id).id for row in credentials]
    return {"status": "QUEUED", "task_ids": task_ids, "credential_count": len(task_ids), "connection_id": connection_id}
