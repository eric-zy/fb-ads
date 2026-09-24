"""可复用的地区组和定向包。"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, JSON, String, Text

from core.database import Base
from core.tenant import TenantMixin


class RegionGroup(TenantMixin, Base):
    """XMP 风格的地区组，只保存 Meta targeting 所需的地区 ID。"""

    __tablename__ = "region_groups"
    __table_args__ = (
        Index("ix_region_groups_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    geo_locations = Column(JSON, nullable=False, default=dict)
    excluded_geo_locations = Column(JSON, nullable=False, default=dict)
    account_ids = Column(JSON, nullable=False, default=list, comment="允许绑定的系统广告账户主键")
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    description = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "geo_locations": self.geo_locations or {},
            "excluded_geo_locations": self.excluded_geo_locations or {},
            "account_ids": self.account_ids or [],
            "status": self.status,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TargetingPackage(TenantMixin, Base):
    """XMP 风格的可复用定向包，包含受众、设备、语言和版位。"""

    __tablename__ = "targeting_packages"
    __table_args__ = (
        Index("ix_targeting_packages_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    targeting_json = Column(JSON, nullable=False, default=dict)
    placement_json = Column(JSON, nullable=False, default=dict)
    account_ids = Column(JSON, nullable=False, default=list, comment="允许绑定的系统广告账户主键")
    region_group_ids = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    description = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "targeting_json": self.targeting_json or {},
            "placement_json": self.placement_json or {},
            "account_ids": self.account_ids or [],
            "region_group_ids": self.region_group_ids or [],
            "status": self.status,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
