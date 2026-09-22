from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, JSON, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class MetaTrackingAsset(TenantMixin, Base):
    """按广告账户保存 Pixel / Dataset 元数据，不保存事件或用户数据。"""

    __tablename__ = "meta_tracking_assets"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "meta_asset_id", "asset_type", name="uq_meta_tracking_account_asset"),
        Index("ix_meta_tracking_tenant_account", "tenant_id", "ad_account_id"),
        Index("ix_meta_tracking_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), nullable=False, index=True, comment="系统广告账户主键")
    meta_ad_account_id = Column(String(64), nullable=False, index=True, comment="Meta act_xxx")
    meta_asset_id = Column(String(128), nullable=False, comment="Meta Pixel/Dataset ID")
    asset_type = Column(String(32), nullable=False, comment="PIXEL / DATASET")
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE", server_default="ACTIVE")
    usable = Column(Boolean, nullable=False, default=True, server_default="true")
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)
    raw_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ad_account_id": self.ad_account_id,
            "meta_ad_account_id": self.meta_ad_account_id,
            "meta_asset_id": self.meta_asset_id,
            "name": self.name,
            "asset_type": self.asset_type,
            "status": self.status,
            "usable": bool(self.usable),
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_sync_error": self.last_sync_error,
            "raw_json": self.raw_json or {},
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
