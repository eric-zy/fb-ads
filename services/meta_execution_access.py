"""Account-scoped execution delegation; never transfers OAuth ownership."""
from datetime import datetime

from sqlalchemy import or_
from models import MetaConnection, MetaConnectionAsset, User, UserAccount
from services.meta_connection_service import connection_health

HEALTHY_CONNECTIONS = {"ACTIVE", "EXPIRING", "EXPIRING_1_DAY"}
WRITE_ACCOUNT_ROLES = {"owner", "manager", "editor", "operator", "publisher"}


def delegated_assignments(db, user):
    return db.query(UserAccount).filter(
        UserAccount.tenant_id == user.tenant_id, UserAccount.user_id == user.id,
        UserAccount.assignment_status == "ACTIVE",
        UserAccount.role.in_(WRITE_ACCOUNT_ROLES),
        UserAccount.execution_connection_id.isnot(None),
        or_(UserAccount.expires_at.is_(None), UserAccount.expires_at > datetime.utcnow()),
    ).all()


def delegated_connection_id(db, user, account):
    return next((row.execution_connection_id for row in delegated_assignments(db, user)
                 if row.account_id == account.id and row.tenant_id == account.tenant_id), None)


def execution_candidates(db, account):
    grants = db.query(MetaConnectionAsset).filter_by(
        tenant_id=account.tenant_id, asset_type="AD_ACCOUNT", asset_id=account.id, status="ACTIVE",
    ).all()
    rows = db.query(MetaConnection).filter(
        MetaConnection.tenant_id == account.tenant_id,
        MetaConnection.id.in_([g.connection_id for g in grants]),
    ).all()
    result = []
    for row in rows:
        owner = db.query(User).filter_by(id=row.authorized_by_user_id, tenant_id=account.tenant_id, is_active=True).first()
        if not owner or not row.credential_id or connection_health(row) not in HEALTHY_CONNECTIONS:
            continue
        if row.access_mode == "direct":
            from models import Credential
            cred = db.query(Credential).filter_by(id=row.credential_id, connection_id=row.id, status="ACTIVE").first()
            if not cred or cred.is_expired():
                continue
        pages = db.query(MetaConnectionAsset).filter_by(connection_id=row.id, asset_type="PAGE", status="ACTIVE").all()
        from services.meta.page_access import ADVERTISING_PAGE_TASKS
        result.append({"connection_id": row.id, "meta_user_id": row.meta_user_id,
            "authorized_by_user_id": owner.id, "authorized_by_username": owner.username,
            "health": connection_health(row), "page_count": sum(
                bool({str(x).upper() for x in g.tasks or []} & ADVERTISING_PAGE_TASKS) for g in pages),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None})
    return result
