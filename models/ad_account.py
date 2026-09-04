"""广告账户模型（Meta 账号管理 V1 —— 设计文档 §6 / §7 / §9）

三条核心约定：

1. **Meta 状态与系统状态分离**（文档 §7）
    - `account_status` / `effective_status`：Meta 返回的原始状态，同步时覆盖
    - `system_status`：系统侧是否允许参与批量投放，**同步绝不能覆盖**
   两者组合的含义：
      Meta ACTIVE  + System ACTIVE   = 正常可投
      Meta DISABLED+ System ACTIVE   = Meta 异常，系统未干预
      Meta ACTIVE  + System DISABLED = Meta 正常，管理员禁止投放

2. **金额一律 BIGINT 最小货币单位**（文档 §9）
   $10.50 → 1050。换算见 `core/money.py`。
   ctr/cpc/cpm/roas/risk_score 是派生指标不是金额，保持浮点。

3. **归属唯一键 = (business_id, account_id)**（文档 §24 Upsert 规则）
   允许同一个 act_xxx 挂在多个 BM 下（代理场景），同一个 BM 内不重复。
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

# 能力扩展字段：PostgreSQL 用 JSONB（支持 GIN 索引与包含查询），
# 其余方言（测试用的 SQLite）退化为普通 JSON，保证同一套模型跨库可用。
JSONVariant = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")
import enum

from core.database import Base
from core.tenant import TenantMixin


class AccountStatus(str, enum.Enum):
    """【遗留】账户状态枚举

    已被 `system_status` + `account_status` 取代，仅为兼容历史导入保留，
    新代码请使用 SystemStatus。
    """

    ACTIVE = "active"
    FROZEN = "frozen"
    PAUSED = "paused"
    SUSPENDED = "suspended"


class SystemStatus(str, enum.Enum):
    """系统侧状态（文档 §7）：是否允许该账户参与批量投放"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AdAccount(TenantMixin, Base):
    """Facebook 广告账户（租户级核心资产）"""

    __tablename__ = "ad_accounts"

    id = Column(String(50), primary_key=True, index=True)

    # ---------- 归属 BM ----------
    business_id = Column(
        String(50),
        ForeignKey("meta_accounts.id"),
        nullable=False,
        index=True,
        comment="所属 BM（businesses / meta_accounts）",
    )
    business = relationship("MetaAccount", back_populates="ad_accounts")

    # ---------- Meta 侧基础信息 ----------
    account_id = Column(String(64), nullable=False, comment="Meta 广告账户 ID（act_xxx）")
    account_name = Column(String(255))
    account_status = Column(String(32), comment="Meta 返回的账户状态")
    effective_status = Column(String(32), comment="Meta 有效状态")
    currency = Column(String(16), default="USD")
    timezone = Column(String(64))

    # ---------- Meta 侧金额（最小货币单位） ----------
    spend_cap = Column(BigInteger, default=0, comment="Meta 消费上限")
    amount_spent = Column(BigInteger, default=0, comment="累计消费")
    balance = Column(BigInteger, default=0, comment="当前余额")
    disable_reason = Column(String(255), comment="Meta 侧禁用原因")

    # ---------- 系统侧状态（同步不得覆盖） ----------
    system_status = Column(
        String(32),
        default=SystemStatus.ACTIVE.value,
        nullable=False,
        comment="系统是否允许参与批量投放：ACTIVE / DISABLED",
    )
    system_status_reason = Column(String(500), comment="系统侧禁用原因（如风控冻结）")
    system_status_at = Column(DateTime, comment="最近一次系统侧状态变更时间")
    capabilities = Column(
        JSONVariant,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
        comment="能力扩展字段（文档 §8）：can_create_campaign / can_read_insights 等",
    )

    # ---------- 系统侧限额（风控用，最小货币单位） ----------
    daily_spend_limit = Column(BigInteger, default=0, nullable=False)
    monthly_spend_limit = Column(BigInteger, default=0, nullable=False)

    # ---------- 风控 ----------
    risk_score = Column(Float, default=0.0, comment="0-1.0")
    last_risk_check = Column(DateTime)

    # ---------- 同步 ----------
    last_synced_at = Column(DateTime)
    last_sync_error = Column(Text)

    # ---------- 关联 ----------
    campaigns = relationship("Campaign", back_populates="ad_account", cascade="all, delete-orphan")
    insights = relationship("AccountInsight", back_populates="ad_account", cascade="all, delete-orphan")
    risk_events = relationship("RiskEvent", back_populates="ad_account", cascade="all, delete-orphan")

    # ---------- 元数据 ----------
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # 文档 §24：同一 BM 内账户不重复；跨 BM 允许同一 act_xxx
        UniqueConstraint("business_id", "account_id", name="uq_business_account"),
        Index("ix_ad_accounts_account_id", "account_id"),
        # ---- 租户隔离复合索引：行级隔离下索引必须以 tenant_id 打头 ----
        Index("ix_ad_accounts_tenant_business", "tenant_id", "business_id"),
        Index("ix_ad_accounts_tenant_system_status", "tenant_id", "system_status"),
        Index("ix_ad_accounts_tenant_account_status", "tenant_id", "account_status"),
        Index("ix_ad_accounts_tenant_effective", "tenant_id", "effective_status"),
    )

    # ---------- 兼容属性 ----------
    @property
    def is_frozen(self) -> bool:
        """兼容旧字段：系统侧禁用即视为冻结

        注意：这是只读派生属性，**不能用于数据库查询过滤**
        （过滤请用 `AdAccount.system_status == SystemStatus.DISABLED.value`）。
        """
        return self.system_status == SystemStatus.DISABLED.value

    def __repr__(self):
        return f"<AdAccount {self.account_id} ({self.account_name})>"
