from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from core.database import Base
from core.tenant import TenantMixin


creative_asset_group_members = Table(
    "creative_asset_group_members",
    Base.metadata,
    Column("group_id", String(50), ForeignKey("creative_asset_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", String(50), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("can_edit", Boolean, nullable=False, server_default="false"),
)


class CreativeAssetGroup(TenantMixin, Base):
    __tablename__ = "creative_asset_groups"

    id = Column(String(50), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    visibility = Column(String(20), nullable=False, server_default="PRIVATE")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    owner = relationship("User", foreign_keys=[owner_id])
    members = relationship("User", secondary=creative_asset_group_members, viewonly=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_creative_asset_groups_tenant_name"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "visibility": self.visibility,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
