"""统一运维视图：同步任务、凭据健康和操作审计。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.auth import require_admin
from core.database import get_db
from models import AuditLog, Credential, MetaSyncLog, User
from core.enums import CredentialStatus
from datetime import datetime

router = APIRouter(prefix="/api/v1/operations", tags=["运营与审计"])


@router.get("/sync-tasks")
def list_sync_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(MetaSyncLog)
    if status:
        query = query.filter(MetaSyncLog.status == status)
    rows = query.order_by(MetaSyncLog.created_at.desc()).limit(limit).all()
    return [row.to_dict() for row in rows]


@router.get("/credential-health")
def credential_health(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.query(Credential).order_by(Credential.updated_at.desc()).all()
    now = datetime.utcnow()
    result = []
    for row in rows:
        expires = row.expires_at
        if row.status == CredentialStatus.EXPIRED.value or (expires and expires < now):
            health = "EXPIRED"
        elif row.status != CredentialStatus.ACTIVE.value:
            health = row.status
        elif row.last_error:
            health = "ERROR"
        else:
            health = "ACTIVE"
        result.append({
            "id": row.id,
            "meta_account_id": row.meta_account_id,
            "token_type": row.token_type,
            "source": row.source,
            "status": row.status,
            "health": health,
            "scopes": row.scopes or [],
            "expires_at": expires.isoformat() if expires else None,
            "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
            "last_error": row.last_error,
        })
    return result


@router.get("/audit-logs")
def list_audit_logs(
    resource_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(AuditLog)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if action:
        query = query.filter(AuditLog.action == action)
    return [row.to_dict() for row in query.order_by(AuditLog.created_at.desc()).limit(limit).all()]
