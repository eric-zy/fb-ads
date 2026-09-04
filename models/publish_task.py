from sqlalchemy import BigInteger, Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base
from core.tenant import TenantMixin


class PublishTask(TenantMixin, Base):
    """一次批量发布任务

    组合 = 账户 × 素材 × 文案。任务记录总体进度与摘要。
    """

    __tablename__ = "publish_tasks"

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), comment="任务名称（用户填写）")

    # 配置快照
    account_ids = Column(Text, comment="账户 id 列表，JSON")
    asset_ids = Column(Text, comment="素材 id 列表，JSON")
    copies = Column(Text, comment="文案列表，JSON")
    objective = Column(String(50), default="OUTCOME_SALES")
    daily_budget = Column(BigInteger, comment="日预算（最小货币单位，见 core/money.py）")
    name_prefix = Column(String(100))

    # 进度
    total = Column(Integer, default=0, comment="组合总数")
    success = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String(20), default="running", comment="running / done / partial")
    dev_mode = Column(Boolean, default=False, comment="是否为开发降级模式（未真实提交 FB）")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("PublishedAd", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_publish_tasks_tenant_created", "tenant_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "status": self.status,
            "dev_mode": self.dev_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PublishedAd(TenantMixin, Base):
    """批量发布中单条组合的结果"""

    __tablename__ = "published_ads"
    __table_args__ = (
        Index("ix_published_ads_tenant_task", "tenant_id", "task_id"),
    )

    id = Column(String(50), primary_key=True, index=True)
    task_id = Column(String(50), ForeignKey("publish_tasks.id"), index=True)

    account_id = Column(String(50), comment="目标广告账户 id")
    asset_id = Column(String(50), nullable=True, comment="引用的素材 id")
    asset_type = Column(String(20))
    headline = Column(String(255))
    body = Column(Text)

    # FB 返回的真实/虚拟 id
    fb_campaign_id = Column(String(100))
    fb_adset_id = Column(String(100))
    fb_ad_id = Column(String(100))

    status = Column(String(20), default="success", comment="success / failed")
    error = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("PublishTask", back_populates="items")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "account_id": self.account_id,
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "headline": self.headline,
            "body": self.body,
            "fb_campaign_id": self.fb_campaign_id,
            "fb_adset_id": self.fb_adset_id,
            "fb_ad_id": self.fb_ad_id,
            "status": self.status,
            "error": self.error,
        }
