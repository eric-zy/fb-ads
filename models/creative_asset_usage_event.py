from datetime import datetime

from sqlalchemy import Column, DateTime, Index, JSON, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class CreativeAssetUsageEvent(TenantMixin, Base):
    """素材被用于投放时记录的不可变事件。"""

    __tablename__ = "creative_asset_usage_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_key", name="uq_asset_usage_event_key"),
        Index("ix_asset_usage_events_tenant_asset_time", "tenant_id", "asset_id", "occurred_at"),
        Index("ix_asset_usage_events_tenant_account_time", "tenant_id", "ad_account_id", "occurred_at"),
    )

    id = Column(String(50), primary_key=True, index=True)
    event_key = Column(String(150), nullable=False)
    asset_id = Column(String(50), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, default="PUBLISH")
    status = Column(String(20), nullable=False, comment="PENDING / SUCCESS / FAILED")
    publish_task_id = Column(String(50), nullable=True, index=True)
    published_ad_id = Column(String(50), nullable=True, index=True)
    ad_account_id = Column(String(50), nullable=True, index=True)
    actor_id = Column(String(50), nullable=True, index=True)
    external_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "event_type": self.event_type,
            "status": self.status,
            "publish_task_id": self.publish_task_id,
            "published_ad_id": self.published_ad_id,
            "ad_account_id": self.ad_account_id,
            "actor_id": self.actor_id,
            "external_id": self.external_id,
            "error_message": self.error_message,
            "details": self.details,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
        }
