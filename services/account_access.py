"""当前用户可用广告账户的统一权限查询。"""

from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.tenant import effective_tenant_id
from models import AdAccount, User, UserAccount
from models.account_group import AccountGroup, account_group_accounts, account_group_users


def accessible_account_ids(db: Session, user: User) -> Optional[set[str]]:
    """返回用户当前可操作的广告账户内部 ID。

    管理员返回 ``None`` 表示不限制；普通用户只返回当前租户内仍有效的
    直接分配和账户组分配。过期或已撤销的关系不能继续用于素材、报表等业务。
    """
    if user.is_admin():
        return None

    tenant_id = effective_tenant_id(user)
    now = datetime.utcnow()
    assignment_query = db.query(UserAccount.account_id).filter(
        UserAccount.user_id == user.id,
        UserAccount.assignment_status == "ACTIVE",
        or_(UserAccount.expires_at.is_(None), UserAccount.expires_at > now),
    )
    if tenant_id:
        assignment_query = assignment_query.filter(UserAccount.tenant_id == tenant_id)
    direct = {row[0] for row in assignment_query.all()}

    group_query = (
        db.query(account_group_accounts.c.account_id)
        .join(
            account_group_users,
            account_group_users.c.group_id == account_group_accounts.c.group_id,
        )
        .join(AccountGroup, AccountGroup.id == account_group_accounts.c.group_id)
        .join(AdAccount, AdAccount.id == account_group_accounts.c.account_id)
        .filter(account_group_users.c.user_id == user.id)
    )
    if tenant_id:
        group_query = group_query.filter(
            AccountGroup.tenant_id == tenant_id,
            AdAccount.tenant_id == tenant_id,
        )
    grouped = {row[0] for row in group_query.all()}
    return direct | grouped


def can_access_account(db: Session, user: User, account_id: str) -> bool:
    """检查当前用户是否能访问指定广告账户。"""
    visible = accessible_account_ids(db, user)
    return visible is None or account_id in visible
