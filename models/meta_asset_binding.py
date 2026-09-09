from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Index, UniqueConstraint, Integer
from core.database import Base
from core.tenant import TenantMixin


class MetaAssetBinding(TenantMixin, Base):
    """系统素材在具体 Meta 广告账户下的资源映射。"""

    __tablename__ = "meta_asset_bindings"
    __table_args__ = (
        UniqueConstraint("asset_id", "ad_account_id", name="uq_meta_asset_account"),
        Index("ix_meta_asset_bindings_tenant_asset", "tenant_id", "asset_id"),
        Index("ix_meta_asset_bindings_tenant_account", "tenant_id", "ad_account_id"),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(String(50), nullable=False, index=True)
    ad_account_id = Column(String(50), nullable=False, index=True)
    meta_asset_id = Column(String(255), nullable=True)
    meta_asset_type = Column(String(20), nullable=False)
    status = Column(String(20), default="PENDING", nullable=False)
    error_message = Column(Text)
    uploaded_at = Column(DateTime)
    last_verified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    retry_count = Column(Integer, default=0, nullable=False)
    processing_status = Column(String(30), nullable=True)
    error_code = Column(String(80), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "ad_account_id": self.ad_account_id,
            "meta_asset_id": self.meta_asset_id,
            "meta_asset_type": self.meta_asset_type,
            "status": self.status,
            "error_message": self.error_message,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "retry_count": self.retry_count,
            "processing_status": self.processing_status,
            "error_code": self.error_code,
        }
