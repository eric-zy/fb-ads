"""BM 主账号模型（Meta 账号管理 V1 —— 设计文档 §5）

对应文档中的 `businesses` 表。表名沿用 `meta_accounts` 以维持既有 API 路径
（`/api/v1/meta-accounts`）与外键引用，字段按文档补齐。

关键约定：

1. **BM 不存明文 Token**
   Access Token 一律加密存 `credentials` 表，BM 只保存主数据。
   凭据由 CredentialService 按 BM 解析（见 services/credential_service.py）。

2. **status 与 sync_status 分离**（文档 §5）
    - `status`：业务状态（ACTIVE / DISABLED / ARCHIVED），人工维护
    - `sync_status`：最近一次同步状态（PENDING / SYNCING / SUCCESS / FAILED），同步任务维护
   两者不能混用。

3. **凭据关系方向**
   `credentials.meta_account_id` → 本表。即一个 BM 可拥有多条凭据
   （轮换时旧的转 DISABLED 留痕），而非"BM 指向单个默认凭据"。
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from core.database import Base
from core.tenant import TenantMixin


class BusinessStatus(str, enum.Enum):
    """BM 系统侧状态（文档 §5）"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class SyncStatus(str, enum.Enum):
    """同步状态（文档 §5）—— 与业务状态分离，不可混用"""

    PENDING = "PENDING"
    SYNCING = "SYNCING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class MetaAccount(TenantMixin, Base):
    """Meta 主账号（Business Manager）

    多租户改造：唯一约束由 `business_id` 全局唯一改为
    `(tenant_id, business_id)` 唯一——同一个 BM 在代理/外包场景下
    可能被多个租户各自录入，租户内不允许重复即可。
    """

    __tablename__ = "meta_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "business_id", name="uq_tenant_business"),
        Index("ix_meta_accounts_tenant_status", "tenant_id", "status"),
        Index("ix_meta_accounts_tenant_sync", "tenant_id", "sync_status"),
    )

    id = Column(String(50), primary_key=True, index=True)

    # ---------- 基础信息 ----------
    name = Column(String(255), nullable=False, comment="BM 显示名称")
    business_id = Column(
        String(64), nullable=False, comment="Meta Business ID（租户内唯一）"
    )
    app_id = Column(String(128), comment="Meta App ID")

    # ---------- Meta 侧属性 ----------
    timezone = Column(String(64), comment="BM 时区")
    currency = Column(String(16), comment="BM 默认货币")
    description = Column(Text, comment="备注")

    # ---------- 业务状态（人工维护） ----------
    status = Column(
        String(32),
        default=BusinessStatus.ACTIVE.value,
        nullable=False,
        comment="ACTIVE / DISABLED / ARCHIVED",
    )

    # ---------- 同步状态（同步任务维护） ----------
    sync_status = Column(
        String(32),
        default=SyncStatus.PENDING.value,
        nullable=False,
        comment="PENDING / SYNCING / SUCCESS / FAILED",
    )
    last_synced_at = Column(DateTime, comment="最近成功同步时间")
    last_sync_error = Column(Text, comment="最近同步错误")

    # ---------- 既有功能：默认主账号 ----------
    is_default = Column(Boolean, default=False, comment="是否为默认主账号")

    # ---------- 默认凭据（文档 §5 credential_id） ----------
    # 反向设计下（1 BM → N 凭据），原先只能按"最新一条 ACTIVE"推导默认凭据，
    # 管理员无法显式指定、多条并存时结果取决于创建时间。
    # 该字段让默认凭据可显式指定；为空时仍回退到原推导逻辑，向后兼容。
    # use_alter=True：与 credentials.meta_account_id 构成双向外键，
    # 必须延后到 ALTER 阶段建约束，否则 create_all 会因循环依赖失败。
    default_credential_id = Column(
        String(50),
        ForeignKey("credentials.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        comment="默认凭据 ID；为空则回退为「最新一条 ACTIVE 凭据」",
    )
    default_credential = relationship(
        "Credential", foreign_keys=[default_credential_id]
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ---------- 关联 ----------
    ad_accounts = relationship("AdAccount", back_populates="business", cascade="save-update")

    @property
    def is_active(self) -> bool:
        """兼容旧字段：业务状态为 ACTIVE 即启用"""
        return self.status == BusinessStatus.ACTIVE.value

    def to_dict(self, include_secret: bool = False) -> dict:
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "business_id": self.business_id,
            "app_id": self.app_id,
            "timezone": self.timezone,
            "currency": self.currency,
            "description": self.description,
            "status": self.status,
            "is_active": self.is_active,
            "sync_status": self.sync_status,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_sync_error": self.last_sync_error,
            "is_default": bool(self.is_default),
            "account_count": len(self.ad_accounts) if self.ad_accounts else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        return data

    def __repr__(self):
        return f"<MetaAccount {self.business_id} ({self.name})>"
