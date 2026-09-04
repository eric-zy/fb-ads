"""用户与用户-账户关联模型

多租户改造要点（迁移 0006）：
    - `users.tenant_id` 可为空：平台管理员不属于任何租户，需要跨租户操作
    - `role` 由自由字符串升级为 `UserRole` 枚举（platform_admin / tenant_admin /
      manager / user），历史值 `admin` 由 `UserRole.normalize()` 兜底为 tenant_admin
    - `company_id` 保留但已废弃，仅为兼容老前端，新代码一律用 `tenant_id`
"""

from sqlalchemy import Column, String, DateTime, Boolean, JSON, Index
from datetime import datetime

from core.database import Base
from core.tenant import TenantMixin
from models.tenant import UserRole


class User(TenantMixin, Base):
    """用户模型（租户成员）

    租户归属：绝大多数用户必须属于某个 `Tenant`；
    仅平台运营账号（platform_admin）`tenant_id` 可为 NULL，用于跨租户管理。
    """

    __tablename__ = "users"
    __tenant_nullable__ = True  # 平台管理员可跨租户，允许为空

    id = Column(String(50), primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)

    # 【废弃】company_id 已被 tenant_id 取代，仅保留字段兼容历史数据/前端
    company_id = Column(String(50), index=True)
    role = Column(String(50), default=UserRole.USER.value)  # 见 UserRole

    # 权限
    permissions = Column(JSON, default=[])
    settings = Column(JSON, default={})

    # 状态
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    __table_args__ = (
        Index('ix_email_active', 'email', 'is_active'),
        # 租户内成员列表：按租户 + 状态过滤
        Index('ix_users_tenant_active', 'tenant_id', 'is_active'),
    )

    def is_platform_admin(self) -> bool:
        return UserRole.is_platform_admin(self.role)

    def is_admin(self) -> bool:
        return UserRole.is_admin(self.role)

    def __repr__(self):
        return f"<User {self.email}>"


class UserAccount(TenantMixin, Base):
    """用户-广告账户关联（租户内可见）"""

    __tablename__ = "user_accounts"

    id = Column(String(50), primary_key=True, index=True)
    user_id = Column(String(50), index=True, nullable=False)
    account_id = Column(String(50), index=True, nullable=False)

    # 权限
    role = Column(String(50), default="viewer")  # owner, editor, viewer

    # 时间戳
    assigned_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_user_account', 'user_id', 'account_id'),
        Index('ix_user_accounts_tenant_user', 'tenant_id', 'user_id'),
    )

    def __repr__(self):
        return f"<UserAccount user={self.user_id} account={self.account_id}>"
