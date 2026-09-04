from sqlalchemy import Column, String, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

from core.database import Base
from core.enums import InstanceStatus
from core.tenant import TenantMixin


class CampaignInstance(TenantMixin, Base):
    """Campaign 实例映射（设计文档第 12 节）

    Template 与 Meta Campaign 之间的映射：
        Template Campaign
            ├── Account A → Campaign 111
            ├── Account B → Campaign 222
            └── Account C → Campaign 333

    唯一约束 (template_id, ad_account_id) 保证同一模板在同一账户不会重复部署，
    这是幂等性的基础（设计文档第 29 节）。
    """

    __tablename__ = "campaign_instances"
    __table_args__ = (
        UniqueConstraint("template_id", "ad_account_id", name="uq_template_account_campaign"),
        Index("ix_campaign_instances_tenant_template", "tenant_id", "template_id"),
        Index("ix_campaign_instances_tenant_account", "tenant_id", "ad_account_id"),
    )

    id = Column(String(50), primary_key=True, index=True)
    template_id = Column(String(50), ForeignKey("campaign_templates.id"), nullable=False, index=True)
    ad_account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False, index=True)

    meta_campaign_id = Column(String(128), index=True, comment="Meta 侧 Campaign ID")
    name = Column(String(255))

    status = Column(String(32), default=InstanceStatus.PAUSED.value, comment="本地状态 ACTIVE / PAUSED / ARCHIVED / DELETED")
    meta_status = Column(String(32), comment="Meta 侧状态同步，如 ACTIVE / PAUSED")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = relationship("CampaignTemplate", back_populates="instances")
    ad_account = relationship("AdAccount")
    adsets = relationship("AdSetInstance", back_populates="campaign_instance", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "template_id": self.template_id,
            "ad_account_id": self.ad_account_id,
            "meta_campaign_id": self.meta_campaign_id,
            "name": self.name,
            "status": self.status,
            "meta_status": self.meta_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AdSetInstance(TenantMixin, Base):
    """AdSet 实例（设计文档第 13 节）"""

    __tablename__ = "adset_instances"
    __table_args__ = (
        Index("ix_adset_instances_tenant_campaign", "tenant_id", "campaign_instance_id"),
    )

    id = Column(String(50), primary_key=True, index=True)
    campaign_instance_id = Column(
        String(50), ForeignKey("campaign_instances.id"), nullable=False, index=True
    )

    meta_adset_id = Column(String(128), index=True, comment="Meta 侧 AdSet ID")
    name = Column(String(255))
    status = Column(String(32), default=InstanceStatus.PAUSED.value)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign_instance = relationship("CampaignInstance", back_populates="adsets")
    ads = relationship("AdInstance", back_populates="adset_instance", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "campaign_instance_id": self.campaign_instance_id,
            "meta_adset_id": self.meta_adset_id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AdInstance(TenantMixin, Base):
    """Ad 实例（设计文档第 14 节）"""

    __tablename__ = "ad_instances"
    __table_args__ = (
        Index("ix_ad_instances_tenant_adset", "tenant_id", "adset_instance_id"),
    )

    id = Column(String(50), primary_key=True, index=True)
    adset_instance_id = Column(
        String(50), ForeignKey("adset_instances.id"), nullable=False, index=True
    )
    # 复用现有素材表 creative_assets（系统素材），记录跨账户的 Meta 素材 ID
    creative_id = Column(String(50), ForeignKey("creative_assets.id"), nullable=True)

    meta_ad_id = Column(String(128), index=True, comment="Meta 侧 Ad ID")
    name = Column(String(255))
    status = Column(String(32), default=InstanceStatus.PAUSED.value)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    adset_instance = relationship("AdSetInstance", back_populates="ads")
    creative = relationship("CreativeAsset")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "adset_instance_id": self.adset_instance_id,
            "creative_id": self.creative_id,
            "meta_ad_id": self.meta_ad_id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
