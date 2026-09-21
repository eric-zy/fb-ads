"""风控动作的错误分类和基础设施告警辅助函数。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.logger import logger
from models import SyncAlert
from services.credential_service import CredentialError, CredentialExpiredError
from services.fb_connector_client import FBConnectorError


def classify_risk_error(exc: Exception) -> str:
    """把底层异常归一为前端和运营可以直接处理的错误码。"""
    if isinstance(exc, (CredentialExpiredError, CredentialError)):
        return "CREDENTIAL_EXPIRED" if isinstance(exc, CredentialExpiredError) else "CREDENTIAL_MISSING"
    if isinstance(exc, FBConnectorError):
        status = getattr(exc, "status_code", None)
        return {
            401: "CREDENTIAL_INVALID",
            403: "PERMISSION_DENIED",
            404: "TARGET_NOT_FOUND",
            409: "TARGET_STATE_CONFLICT",
            429: "RATE_LIMITED",
        }.get(status, "PROVIDER_UNAVAILABLE" if status and status >= 500 else "CONNECTOR_ERROR")
    if isinstance(exc, ValueError) and any(word in str(exc).lower() for word in ("凭据", "credential", "token")):
        return "CREDENTIAL_MISSING"
    if isinstance(exc, TimeoutError):
        return "PROVIDER_TIMEOUT"
    return "INTERNAL_ERROR"


def upsert_operational_alert(
    db: Session,
    *,
    tenant_id: str,
    alert_type: str,
    title: str,
    message: str,
    ad_account_id: Optional[str] = None,
) -> tuple[SyncAlert, bool]:
    """创建一条未解决的运营告警；同类未解决告警只保留一条。"""
    query = db.query(SyncAlert).filter(
        SyncAlert.tenant_id == tenant_id,
        SyncAlert.alert_type == alert_type,
        SyncAlert.title == title,
        SyncAlert.is_resolved.is_(False),
    )
    query = query.filter(
        SyncAlert.ad_account_id.is_(None) if ad_account_id is None else SyncAlert.ad_account_id == ad_account_id
    )
    existing = query.first()
    if existing:
        existing.message = message
        db.commit()
        return existing, False

    alert = SyncAlert(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        ad_account_id=ad_account_id,
        alert_type=alert_type,
        title=title,
        message=message,
    )
    db.add(alert)
    db.commit()
    return alert, True


def resolve_operational_alerts(db: Session, *, tenant_id: str, alert_type: str) -> int:
    """依赖恢复后关闭对应的未解决告警。"""
    alerts = db.query(SyncAlert).filter(
        SyncAlert.tenant_id == tenant_id,
        SyncAlert.alert_type == alert_type,
        SyncAlert.is_resolved.is_(False),
    ).all()
    for alert in alerts:
        alert.is_resolved = True
        alert.resolved_at = datetime.utcnow()
    if alerts:
        db.commit()
    return len(alerts)


def check_database(db: Session) -> None:
    db.execute(text("SELECT 1"))


def log_dependency_failure(name: str, exc: Exception) -> None:
    logger.error("[risk-health] dependency=%s unavailable error=%s", name, str(exc)[:500])
