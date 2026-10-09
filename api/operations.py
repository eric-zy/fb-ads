"""统一运维视图：同步任务、凭据健康和操作审计。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.auth import require_admin
from core.database import get_db
from config.settings import settings
from models import AuditLog, Credential, MetaSyncLog, User
from core.enums import CredentialStatus
from datetime import datetime, timezone
import requests

router = APIRouter(prefix="/api/v1/operations", tags=["运营与审计"])


@router.get("/health")
def system_health(_: User = Depends(require_admin)):
    """Return safe dependency probes for the admin operations page."""
    from core.database import engine
    from core.redis_client import redis_client
    from services.readiness import dependency_readiness

    readiness = dependency_readiness(engine, redis_client.redis_client)
    checks = dict(readiness.get("checks") or {})

    try:
        from celery_app import celery_app
        replies = celery_app.control.inspect(timeout=1.0).ping() or {}
        worker_names = sorted(replies)
        checks["celery_workers"] = "ok" if worker_names else "unavailable"
    except Exception:
        worker_names = []
        checks["celery_workers"] = "unavailable"

    connector = {"status": "not_required", "checks": {}}
    if settings.FB_ACCESS_MODE == "connector":
        from services.fb_connector_client import FBConnectorClient, FBConnectorError

        components = ("database", "redis", "oauth_receipt_signing")
        connector = {"status": "unavailable", "checks": {key: "unavailable" for key in components}}
        connector["checks"]["service_auth"] = "unavailable"
        timeout = max(0.1, min(float(settings.FB_CONNECTOR_TIMEOUT), 5.0))
        ready = False
        try:
            response = requests.get(
                f"{settings.FB_CONNECTOR_BASE_URL.rstrip('/')}/internal/ready",
                timeout=timeout,
            )
            payload = response.json() if response.content else {}
            # Only expose component state, never the Connector's missing-config
            # list or any other deployment details.
            if isinstance(payload, dict) and isinstance(payload.get("checks"), dict):
                remote_checks = payload["checks"]
                for key in components:
                    connector["checks"][key] = "ok" if remote_checks.get(key) == "ok" else "unavailable"
                ready = (response.status_code == 200 and payload.get("status") == "ready"
                         and payload.get("service") == "fb_connector"
                         and all(connector["checks"][key] == "ok" for key in components))
        except (requests.RequestException, ValueError, TypeError):
            pass
        try:
            FBConnectorClient().probe_version(timeout=timeout)
            connector["checks"]["service_auth"] = "ok"
        except (FBConnectorError, ValueError, TypeError):
            pass
        if ready and connector["checks"]["service_auth"] == "ok":
            connector["status"] = "ok"
        checks["connector"] = connector["status"]

    overall = "ready" if all(value == "ok" for value in checks.values()) else "degraded"
    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "celery_workers": worker_names,
        "connector": connector,
    }


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
    if settings.FB_ACCESS_MODE == "connector":
        from services.connector_health import connector_health_rows
        return connector_health_rows(db)
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
    resource_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(AuditLog)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if action:
        query = query.filter(AuditLog.action == action)
    return [row.to_dict() for row in query.order_by(AuditLog.created_at.desc()).limit(limit).all()]
