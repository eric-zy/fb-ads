"""Business authorization; shared account data and private configuration are distinct."""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_

from core.tenant import effective_tenant_id, bypass_tenant
from models import AdAccount, User, UserAccount
from services.account_access import accessible_account_ids


def tenant_required(user):
    tenant_id = effective_tenant_id(user)
    if not tenant_id:
        raise HTTPException(403, "请先切换到目标租户")
    return tenant_id


def owned_query(query, model, user):
    query = query.filter(model.tenant_id == tenant_required(user))
    # Route dependencies always provide a user.  Keep direct service/function
    # calls (used by the existing unit tests and migration tooling) compatible
    # with the pre-ownership API, where ``None`` meant tenant-scoped access.
    if user is not None and not getattr(user, "is_admin", lambda: False)():
        query = query.filter(model.created_by == user.id)
    return query


def account_ids_for_action(db, user, *, write=False):
    tenant_id = tenant_required(user)
    query = db.query(AdAccount.id).filter(AdAccount.tenant_id == tenant_id)
    visible = accessible_account_ids(db, user)
    if visible is not None:
        query = query.filter(AdAccount.id.in_(visible))
    ids = {row[0] for row in query.all()}
    if write and not user.is_admin():
        # Explicit read-only assignments never grant writes, even with a global
        # function permission. Groups retain their existing permission semantics.
        assignments = db.query(UserAccount).filter(
            UserAccount.tenant_id == tenant_id, UserAccount.user_id == user.id,
            UserAccount.assignment_status == "ACTIVE",
            or_(UserAccount.expires_at.is_(None), UserAccount.expires_at > datetime.utcnow()),
        ).all()
        ids -= {row.account_id for row in assignments
                if row.role not in {"owner", "manager", "editor", "operator", "publisher"}}
    return ids


def require_accounts(db, user, ids, *, write=False):
    if not set(ids).issubset(account_ids_for_action(db, user, write=write)):
        raise HTTPException(404, "广告账户不存在或无权操作")


def task_actor(db, user_id, tenant_id):
    # Platform users have no home tenant. Only this identity lookup bypasses
    # tenant filtering; authorization is still evaluated in the task tenant.
    with bypass_tenant():
        user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active or (not user.is_platform_admin() and user.tenant_id != tenant_id):
        raise PermissionError("任务发起用户已失效或不属于当前租户")
    return user
