"""Own authorization management; tenant administrators may inspect all owners."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from core.auth import require_meta_self
from core.database import get_db
from core.tenant import effective_tenant_id
from models import MetaConnection, MetaConnectionAsset, Credential, User, AdAccount
from pydantic import BaseModel, Field
from services.meta_connection_service import owned_connection, connection_health, cancel_connection_jobs

router = APIRouter(prefix="/api/v1/meta-connections", tags=["Meta 授权连接"])


@router.get("")
def list_connections(scope: str = Query("mine", pattern="^(mine|tenant)$"), db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    if scope == "tenant" and not current_user.is_admin():
        raise HTTPException(status_code=403, detail="只有管理员可查看租户全部个人授权")
    q = db.query(MetaConnection).filter_by(tenant_id=effective_tenant_id(current_user))
    if scope == "mine":
        q = q.filter_by(authorized_by_user_id=current_user.id)
    result = []
    for row in q.order_by(MetaConnection.updated_at.desc()).all():
        item = row.to_dict()
        item["health"] = connection_health(row)
        owner = db.query(User).filter_by(id=row.authorized_by_user_id).first()
        item["authorized_by_username"] = owner.username if owner else "用户已删除"
        item["is_owner"] = row.authorized_by_user_id == current_user.id
        grants = db.query(MetaConnectionAsset).filter_by(connection_id=row.id, status="ACTIVE").all()
        for name, kind in (("business_count", "BUSINESS"), ("account_count", "AD_ACCOUNT"), ("page_count", "PAGE")):
            item[name] = sum(g.asset_type == kind for g in grants)
        item["credential_count"] = 1 if row.credential_id else 0
        from services.account_access import accessible_account_ids
        accessible = accessible_account_ids(db, current_user)
        account_ids = [g.asset_id for g in grants if g.asset_type == "AD_ACCOUNT"]
        item["account_names"] = [a.account_name or a.account_id for a in db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()]
        item["executable_account_ids"] = account_ids if current_user.is_admin() else [key for key in account_ids if key in (accessible or set())]
        result.append(item)
    if scope == "tenant":
        # Unowned historical Connector references remain visible for migration,
        # but cannot be claimed or used as another publisher's personal identity.
        from config.settings import settings
        if settings.FB_ACCESS_MODE == "connector":
            from services.connector_health import connector_references
            known = {c.credential_id for c in q.all()}
            for old in connector_references(db):
                if old["id"] in known:
                    continue
                result.append({"id": old["id"], "tenant_id": old["tenant_id"], "meta_user_id": "历史授权",
                    "app_id": "connector", "status": "OWNER_UNKNOWN", "health": "OWNER_UNKNOWN", "scopes": [],
                    "authorized_by_username": "需原投手重新授权确认", "is_owner": False,
                    "business_count": len(old["business_ids"]), "account_count": len(old["account_ids"]),
                    "page_count": len(old["page_ids"]), "credential_count": 1})
    return result


class ExecutionDefaultRequest(BaseModel):
    account_ids: list[str] = Field(min_length=1)


@router.post("/{connection_id}/execution-default")
def choose_execution_identity(connection_id: str, payload: ExecutionDefaultRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    row = owned_connection(db, current_user, connection_id=connection_id, active=True)
    from services.business_access import require_accounts
    require_accounts(db, current_user, payload.account_ids, write=True)
    grants = {g.asset_id for g in db.query(MetaConnectionAsset).filter_by(connection_id=row.id, asset_type="AD_ACCOUNT", status="ACTIVE").all()}
    if not set(payload.account_ids).issubset(grants):
        raise HTTPException(status_code=403, detail="该个人授权不能访问所选广告账户")
    settings = dict(current_user.settings or {})
    selected = dict(settings.get("meta_execution_connections") or {})
    selected.update({key: row.id for key in payload.account_ids})
    settings["meta_execution_connections"] = selected
    current_user.settings = settings
    db.commit()
    from core.audit import record_audit
    record_audit(db, action="SET_PERSONAL_META_EXECUTION", resource_type="meta_connection", resource_id=row.id,
                 user_id=current_user.id, request_data={"account_ids": payload.account_ids})
    return {"success": True, "connection_id": row.id, "account_ids": payload.account_ids}


@router.post("/{connection_id}/reporting-default")
def choose_reporting_identity(connection_id: str, payload: ExecutionDefaultRequest, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="只有管理员可指定系统同步授权")
    row = owned_connection(db, current_user, connection_id=connection_id, active=True, admin=True)
    owner = db.query(User).filter_by(id=row.authorized_by_user_id, is_active=True).first()
    if not owner:
        raise HTTPException(status_code=400, detail="授权所属用户已停用")
    grants = {g.asset_id for g in db.query(MetaConnectionAsset).filter_by(connection_id=row.id, asset_type="AD_ACCOUNT", status="ACTIVE").all()}
    if not set(payload.account_ids).issubset(grants):
        raise HTTPException(status_code=403, detail="所选授权不能访问全部目标账户")
    for account in db.query(AdAccount).filter(AdAccount.id.in_(payload.account_ids)).all():
        account.connection_id = row.id
        account.connector_credential_id = row.credential_id if row.access_mode == "connector" else None
        account.credential_id = row.credential_id if row.access_mode == "direct" else None
    db.commit()
    from core.audit import record_audit
    record_audit(db, action="SET_SYSTEM_META_AUTHORIZATION", resource_type="meta_connection", resource_id=row.id,
                 user_id=current_user.id, request_data={"account_ids": payload.account_ids, "authorization_owner": owner.id})
    return {"success": True, "connection_id": row.id, "account_ids": payload.account_ids}


@router.post("/{connection_id}/sync")
def sync_connection(connection_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    connection = owned_connection(db, current_user, connection_id=connection_id, active=True, admin=True)
    from tasks.meta_sync_tasks import sync_personal_connection_task
    task = sync_personal_connection_task.delay(connection.id, requested_by=current_user.id)
    return {"status": "QUEUED", "task_ids": [task.id], "connection_id": connection.id}


@router.post("/{connection_id}/disconnect")
def disconnect(connection_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_meta_self)):
    row = owned_connection(db, current_user, connection_id=connection_id, admin=True)
    row.status = "REVOKED"
    row.last_error = "平台已解除该个人授权，历史资产与报表保留"
    cancelled = cancel_connection_jobs(db, connection_id=row.id)
    if row.access_mode == "direct":
        for cred in db.query(Credential).filter_by(connection_id=row.id).all():
            cred.status = "DISABLED"
    db.commit()
    from core.audit import record_audit
    record_audit(db, action="DISCONNECT_PERSONAL_META", resource_type="meta_connection", resource_id=row.id,
                 user_id=current_user.id, response_data={"cancelled_jobs": cancelled})
    return {"success": True, "cancelled_jobs": cancelled}
