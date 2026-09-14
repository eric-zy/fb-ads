"""BM 与 Meta 资产的访问关系。"""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from core.database import Base
from core.tenant import TenantMixin

class BusinessAssetAccess(TenantMixin, Base):
    __tablename__ = "business_asset_access"
    id = Column(String(50), primary_key=True, index=True)
    business_id = Column(String(50), ForeignKey("meta_accounts.id"), nullable=False, index=True)
    asset_type = Column(String(32), nullable=False, default="AD_ACCOUNT")
    asset_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False, index=True)
    access_level = Column(String(32), nullable=False, default="READ")
    access_source = Column(String(32), nullable=False, default="PARTNER")
    credential_id = Column(String(50), ForeignKey("credentials.id"), nullable=True, index=True)
    meta_tasks = Column(Text)
    status = Column(String(32), nullable=False, default="ACTIVE")
    last_verified_at = Column(DateTime)
    last_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    business = relationship("MetaAccount", back_populates="asset_accesses")
    asset = relationship("AdAccount", back_populates="access_relations")
    __table_args__ = (UniqueConstraint("tenant_id", "business_id", "asset_type", "asset_id", name="uq_business_asset_access"), Index("ix_asset_access_tenant_business", "tenant_id", "business_id"), Index("ix_asset_access_tenant_asset", "tenant_id", "asset_type", "asset_id"))
