"""账户级 Meta Custom Audience 资产缓存。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class MetaAudienceAsset(TenantMixin, Base):
    __tablename__ = "meta_audience_assets"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "meta_audience_id", name="uq_meta_audience_account"),
        Index("ix_meta_audience_tenant_account", "tenant_id", "ad_account_id"),
        Index("ix_meta_audience_tenant_required", "tenant_id", "is_required_exclusion"),
    )

    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), nullable=False, index=True, comment="系统广告账户主键")
    meta_ad_account_id = Column(String(64), nullable=False, index=True, comment="Meta act_xxx")
    meta_audience_id = Column(String(128), nullable=False)
    name = Column(String(255), nullable=False)
    subtype = Column(String(64), nullable=True)
    delivery_status = Column(String(64), nullable=True)
    sharing_status = Column(String(64), nullable=True)
    source = Column(String(32), nullable=False, default="META", comment="META / LOCAL")
    is_required_exclusion = Column(Boolean, nullable=False, default=False, server_default="false")
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ad_account_id": self.ad_account_id,
            "meta_ad_account_id": self.meta_ad_account_id,
            "meta_audience_id": self.meta_audience_id,
            "name": self.name,
            "subtype": self.subtype,
            "delivery_status": self.delivery_status,
            "sharing_status": self.sharing_status,
            "source": self.source,
            "is_required_exclusion": bool(self.is_required_exclusion),
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_sync_error": self.last_sync_error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
