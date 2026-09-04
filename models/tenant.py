"""租户（Tenant）模型 —— SaaS 多租户的根节点

租户是隔离边界：**一个租户 = 一个客户公司/团队**。
租户下的用户、BM、广告账户、模板、任务、素材互相不可见。

配套文件：
    - `core/tenant.py`    隔离上下文与全局 ORM 过滤钩子
    - `models/user.py`    User 通过 tenant_id 归属租户

设计约定：
    1. 租户不软删除，停用用 `status = SUSPENDED`，归档用 `ARCHIVED`
       （避免误删导致整家公司数据消失）
    2. 配额字段为 NULL 表示**不限制**，0 表示**禁止**
       （别用 0 表示不限，语义容易反）
    3. `slug` 是租户的唯一可读标识，用于子域名 / 登录时选择组织
"""
from datetime import datetime
import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import relationship

from core.database import Base


class TenantStatus(str, enum.Enum):
    """租户状态"""

    ACTIVE = "ACTIVE"        # 正常
    SUSPENDED = "SUSPENDED"  # 欠费 / 违规暂停（只读，禁止投放）
    ARCHIVED = "ARCHIVED"    # 已归档（软删除，数据保留）

    @classmethod
    def is_usable(cls, value: str) -> bool:
        """是否允许业务操作"""
        return value == cls.ACTIVE.value


class TenantPlan(str, enum.Enum):
    """套餐（用于配额与功能开关的默认值）"""

    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class UserRole(str, enum.Enum):
    """用户角色（两层级：平台级 / 租户级）

    platform_admin : 平台运营，可跨租户（配合 bypass_tenant 使用）
    tenant_admin   : 租户管理员，管理本租户全部资源与成员
    manager        : 组长，可创建/发布，不能改成员与配额
    user           : 普通成员，日常投放操作

    历史兼容：早期 `role='admin'` 等价于 `tenant_admin`，
    迁移脚本 0006 已统一改写，代码侧由 `normalize_role()` 兜底。
    """

    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    MANAGER = "manager"
    USER = "user"

    @classmethod
    def normalize(cls, value: str) -> str:
        """把历史/别名角色值归一化为标准枚举值"""
        aliases = {
            "admin": cls.TENANT_ADMIN.value,
            "owner": cls.TENANT_ADMIN.value,
            "superadmin": cls.PLATFORM_ADMIN.value,
            "platform": cls.PLATFORM_ADMIN.value,
        }
        if not value:
            return cls.USER.value
        v = str(value).strip().lower()
        v = aliases.get(v, v)
        return v if v in {r.value for r in cls} else cls.USER.value

    @classmethod
    def is_platform_admin(cls, value: str) -> bool:
        return cls.normalize(value) == cls.PLATFORM_ADMIN.value

    @classmethod
    def is_admin(cls, value: str) -> bool:
        """是否具备管理员权限（平台管理员 + 租户管理员）"""
        return cls.normalize(value) in {
            cls.PLATFORM_ADMIN.value,
            cls.TENANT_ADMIN.value,
        }


class Tenant(Base):
    """租户"""

    __tablename__ = "tenants"

    id = Column(String(50), primary_key=True, index=True)

    # ---------- 基础信息 ----------
    name = Column(String(255), nullable=False, comment="租户名称（公司/团队名）")
    slug = Column(
        String(64),
        nullable=False,
        unique=True,
        comment="租户唯一标识（子域名 / 登录组织码），如 acme",
    )

    status = Column(
        String(32),
        default=TenantStatus.ACTIVE.value,
        nullable=False,
        comment="ACTIVE / SUSPENDED / ARCHIVED",
    )
    plan = Column(
        String(32),
        default=TenantPlan.FREE.value,
        nullable=False,
        comment="FREE / PRO / ENTERPRISE",
    )

    # ---------- 联系人 ----------
    owner_user_id = Column(String(50), comment="租户所有者 user_id（首个管理员）")
    contact_name = Column(String(128))
    contact_email = Column(String(255))

    # ---------- 配额（NULL = 不限制；0 = 禁止） ----------
    max_users = Column(Integer, nullable=True, comment="最大成员数")
    max_meta_accounts = Column(Integer, nullable=True, comment="最大 BM 数")
    max_ad_accounts = Column(Integer, nullable=True, comment="最大广告账户数")
    max_templates = Column(Integer, nullable=True, comment="最大投放模板数")
    max_daily_jobs = Column(Integer, nullable=True, comment="每日最大批量任务数")

    # ---------- 扩展配置 ----------
    features = Column(JSON, default={}, comment="功能开关，如 {'risk_control': true}")
    settings = Column(JSON, default={}, comment="租户级偏好设置（时区/货币/通知）")

    # ---------- 订阅周期 ----------
    expires_at = Column(DateTime, comment="订阅到期时间，NULL 表示长期有效")
    is_trial = Column(Boolean, default=False, comment="是否为试用租户")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ---------- 关联 ----------
    users = relationship(
        "User", back_populates="tenant", cascade="save-update, merge"
    )

    __table_args__ = (
        Index("ix_tenants_slug", "slug"),
        Index("ix_tenants_status", "status"),
    )

    def is_active(self) -> bool:
        """是否可正常使用（未过期 / 未停用）"""
        if not TenantStatus.is_usable(self.status):
            return False
        if self.expires_at and self.expires_at < datetime.utcnow():
            return False
        return True

    def check_quota(self, quota_name: str, current_used: int) -> bool:
        """配额检查：limit 为 None 表示不限"""
        limit = getattr(self, quota_name, None)
        if limit is None:
            return True
        return current_used < limit

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "plan": self.plan,
            "owner_user_id": self.owner_user_id,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "max_users": self.max_users,
            "max_meta_accounts": self.max_meta_accounts,
            "max_ad_accounts": self.max_ad_accounts,
            "max_templates": self.max_templates,
            "max_daily_jobs": self.max_daily_jobs,
            "features": self.features or {},
            "settings": self.settings or {},
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_trial": bool(self.is_trial),
            "is_active": self.is_active(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Tenant {self.slug} ({self.name})>"
