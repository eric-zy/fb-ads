"""Personal OAuth ownership, independent asset grants and execution identity."""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import HTTPException
from models import (MetaConnection, MetaConnectionAsset, Credential, User,
                    UserAccount, CampaignJob, CampaignJobItem, SyncAlert)


def parse_expiry(value):
    if not value or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def connection_health(connection):
    if connection.status != "ACTIVE":
        return connection.status
    now = datetime.utcnow()
    deadlines = [x for x in (connection.expires_at, connection.data_access_expires_at) if x]
    deadline = min(deadlines) if deadlines else None
    if deadline and deadline <= now:
        return "EXPIRED"
    if not {"ads_read", "ads_management"}.issubset(connection.scopes or []):
        return "PERMISSION_MISSING"
    if deadline and deadline <= now + timedelta(days=1):
        return "EXPIRING_1_DAY"
    if deadline and deadline <= now + timedelta(days=7):
        return "EXPIRING"
    return "ACTIVE"


def owned_connection(db, user, *, connection_id=None, credential_id=None, active=False, admin=False):
    from core.tenant import effective_tenant_id
    q = db.query(MetaConnection).filter(MetaConnection.tenant_id == effective_tenant_id(user))
    if connection_id:
        q = q.filter(MetaConnection.id == connection_id)
    else:
        q = q.filter(MetaConnection.credential_id == credential_id)
    row = q.first()
    if not row:
        raise HTTPException(status_code=404, detail="个人 Meta 授权不存在，请重新接入")
    if row.authorized_by_user_id != user.id and not (admin and user.is_admin()):
        raise HTTPException(status_code=403, detail="只能管理自己的 Meta 个人授权")
    if active and connection_health(row) not in {"ACTIVE", "EXPIRING", "EXPIRING_1_DAY"}:
        raise HTTPException(status_code=400, detail="Meta 授权已失效或缺少权限，请重新授权")
    return row


def bind_connection(db, user, result, *, mode, expected_connection_id=None):
    from core.tenant import effective_tenant_id
    tenant_id = effective_tenant_id(user)
    identity = str(result.get("meta_user_id") or "")
    app_id = str(result.get("app_id") or "")
    if not identity or not app_id:
        raise HTTPException(status_code=400, detail="Meta 未返回有效的授权用户与应用信息")
    if expected_connection_id:
        expected = owned_connection(db, user, connection_id=expected_connection_id)
        if expected.meta_user_id != identity or expected.app_id != app_id:
            raise HTTPException(status_code=400, detail="重新授权必须使用原 Meta 个号；其他个号请新增授权")
    row = db.query(MetaConnection).filter_by(tenant_id=tenant_id, meta_user_id=identity, app_id=app_id).first()
    if row and row.authorized_by_user_id not in (None, user.id):
        raise HTTPException(status_code=409, detail="该 Meta 个号已归属于另一用户，请使用自己的 Meta 个号")
    if not row:
        row = MetaConnection(id=uuid.uuid4().hex, tenant_id=tenant_id,
                             meta_user_id=identity, app_id=app_id, authorized_by_user_id=user.id, version=0)
        db.add(row)
    row.version = (row.version or 0) + 1
    row.authorized_by_user_id = user.id
    row.access_mode = mode
    if "credential_id" in result:
        row.credential_id = result["credential_id"]
    row.status = "ACTIVE"
    row.scopes = result.get("scopes") or []
    row.expires_at = parse_expiry(result.get("expires_at"))
    row.data_access_expires_at = parse_expiry(result.get("data_access_expires_at"))
    row.last_error = None
    db.flush()
    return row


def grant_asset(db, connection, asset_type, asset_id, tasks=None):
    row = db.query(MetaConnectionAsset).filter_by(tenant_id=connection.tenant_id,
        connection_id=connection.id, asset_type=asset_type, asset_id=asset_id).first()
    if not row:
        row = MetaConnectionAsset(id=uuid.uuid4().hex, tenant_id=connection.tenant_id,
                                 connection_id=connection.id, asset_type=asset_type, asset_id=asset_id)
        db.add(row)
    row.status = "ACTIVE"
    row.tasks = tasks or []
    row.last_synced_at = datetime.utcnow()
    return row


def cancel_connection_jobs(db, connection_id=None, user_id=None):
    """Cancel unstarted work in the transaction; workers recheck before execution."""
    q = db.query(CampaignJob).filter(CampaignJob.status.in_(["PENDING", "QUEUED"]))
    if user_id:
        q = q.filter(CampaignJob.created_by == user_id)
    if connection_id:
        q = q.join(CampaignJobItem).filter(CampaignJobItem.authorization_connection_id == connection_id)
    count = 0
    for job in q.distinct().all():
        job.status = "CANCELLED"
        job.finished_at = datetime.utcnow()
        job.error_message = "操作人或个人 Meta 授权已停用，请交接账户并使用接手人的授权重新提交"
        for item in job.items:
            if item.status == "PENDING":
                item.status = "SKIPPED"
                item.error_message = job.error_message
        count += 1
    return count


def suspend_user_authorizations(db, user_id):
    count = cancel_connection_jobs(db, user_id=user_id)
    for row in db.query(MetaConnection).filter_by(authorized_by_user_id=user_id).all():
        row.status = "SUSPENDED"
        row.last_error = "平台用户已停用，需要本人重新授权或完成账户交接"
    for row in db.query(UserAccount).filter_by(user_id=user_id, assignment_status="ACTIVE").all():
        row.assignment_status = "REVOKED"
    return count


def inspect_personal_authorizations(db):
    """Persist 7-day/1-day and expiry alerts without changing shared assets."""
    from services.fb_connector_client import FBConnectorClient, FBConnectorError
    from services.risk_reliability import upsert_operational_alert
    rows = db.query(MetaConnection).filter(MetaConnection.status.notin_(["REVOKED", "SUSPENDED"])).all()
    connector_rows = [r for r in rows if r.access_mode == "connector" and r.credential_id]
    for start in range(0, len(connector_rows), 100):
        batch = connector_rows[start:start + 100]
        try:
            summaries = {r["id"]: r for r in FBConnectorClient().credential_health([c.credential_id for c in batch]).get("items", [])}
        except FBConnectorError:
            continue
        for row in batch:
            summary = summaries.get(row.credential_id)
            if summary:
                row.status = summary.get("status") or "INVALID"
                row.scopes = summary.get("scopes") or []
                row.expires_at = parse_expiry(summary.get("expires_at"))
                row.last_error = summary.get("last_error")
    alerts = 0
    for row in rows:
        if row.access_mode == "direct" and row.credential_id:
            cred = db.query(Credential).filter_by(id=row.credential_id).first()
            if not cred or cred.status != "ACTIVE":
                row.status = cred.status if cred else "INVALID"
        health = connection_health(row)
        stage = '1D' if health == 'EXPIRING_1_DAY' else '7D' if health == 'EXPIRING' else 'BAD'
        current_type = f"META_PERSONAL_{row.id}_{stage}"[:64]
        for alert in db.query(SyncAlert).filter(SyncAlert.alert_type.startswith(f"META_PERSONAL_{row.id}_"), SyncAlert.is_resolved.is_(False)).all():
            if health == "ACTIVE" or alert.alert_type != current_type:
                alert.is_resolved = True
                alert.resolved_at = datetime.utcnow()
        if health == "ACTIVE":
            continue
        if health == "EXPIRED":
            row.status = "EXPIRED"
        owner = db.query(User).filter_by(id=row.authorized_by_user_id).first()
        grant = db.query(MetaConnectionAsset).filter_by(connection_id=row.id, asset_type="AD_ACCOUNT", status="ACTIVE").first()
        upsert_operational_alert(db, tenant_id=row.tenant_id, alert_type=current_type,
            title="个人 Meta 授权需要处理", message=f"投手 {owner.username if owner else '已删除用户'} 的 Meta 个号 {row.meta_user_id} 授权状态：{health}，请本人重新授权。",
            ad_account_id=grant.asset_id if grant else None)
        alerts += 1
    db.commit()
    return alerts
