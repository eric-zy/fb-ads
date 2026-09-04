from sqlalchemy import BigInteger, Column, String, Float, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from sqlalchemy import Index
from core.database import Base
from core.enums import TemplateStatus
from core.tenant import TenantMixin


class CampaignTemplate(TenantMixin, Base):
    """投放模板 —— 系统最核心的业务对象（设计文档第 3.1 / 10 节）

    设计要点：
    - "一个 Campaign Template 如何被部署到多个 Ad Account" 是系统的核心抽象，
      而不是 "BM × 广告账户"。
    - 模板配置一次，即可批量部署到 N 个广告账户，
      规模从 20 个账户扩展到 5000 个账户时核心模型不变。
    - Meta 经常变化的参数（定向 / 版位 / 素材文案）放 JSON 字段，
      避免 API 参数变化时频繁改表。
    """

    __tablename__ = "campaign_templates"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False, comment="模板名称，如 US Sales V1")

    # ---- Campaign 级 ----
    objective = Column(String(64), comment="推广目标，如 OUTCOME_SALES / OUTCOME_TRAFFIC")
    buying_type = Column(String(64), default="AUCTION", comment="购买类型")
    special_ad_categories = Column(JSON, comment="特殊广告类别，JSON 数组")

    # ---- 预算（最小货币单位，见 core/money.py） ----
    budget_type = Column(String(32), default="DAILY", comment="DAILY / LIFETIME")
    daily_budget = Column(BigInteger, comment="日预算（最小货币单位）")
    lifetime_budget = Column(BigInteger, comment="总预算（最小货币单位）")

    # ---- 出价与优化 ----
    bid_strategy = Column(String(64), comment="出价策略")
    optimization_goal = Column(String(64), comment="优化目标，如 LINK_CLICKS / OFFSITE_CONVERSIONS")
    billing_event = Column(String(64), comment="计费事件，如 IMPRESSIONS / LINK_CLICKS")

    # ---- Meta 易变参数（设计文档建议 JSONB） ----
    targeting_json = Column(JSON, comment="定向：国家/年龄/性别/兴趣等")
    placement_json = Column(JSON, comment="版位配置")
    creative_config_json = Column(JSON, comment="素材与文案配置（headline/primary_text/description/cta/landing_url）")

    status = Column(String(32), default=TemplateStatus.ACTIVE.value, comment="ACTIVE / DISABLED / ARCHIVED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系：模板 → 批量任务 / 模板 → 各账户的投放实例
    jobs = relationship("CampaignJob", back_populates="template", cascade="save-update")
    instances = relationship("CampaignInstance", back_populates="template", cascade="save-update")

    __table_args__ = (
        # 行级隔离：列表页固定按 (租户, 状态) 过滤
        Index("ix_campaign_templates_tenant_status", "tenant_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "objective": self.objective,
            "buying_type": self.buying_type,
            "special_ad_categories": self.special_ad_categories,
            "budget_type": self.budget_type,
            "daily_budget": self.daily_budget,
            "lifetime_budget": self.lifetime_budget,
            "bid_strategy": self.bid_strategy,
            "optimization_goal": self.optimization_goal,
            "billing_event": self.billing_event,
            "targeting_json": self.targeting_json,
            "placement_json": self.placement_json,
            "creative_config_json": self.creative_config_json,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
