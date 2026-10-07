from sqlalchemy import Column, ForeignKey, Integer, String, Table, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from core.database import Base
from core.tenant import TenantMixin


creative_asset_tag_links = Table(
    "creative_asset_tag_links",
    Base.metadata,
    Column("asset_id", String(50), ForeignKey("creative_assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(50), ForeignKey("creative_asset_tags.id", ondelete="CASCADE"), primary_key=True),
)


class CreativeAssetTagCategory(TenantMixin, Base):
    __tablename__ = "creative_asset_tag_categories"

    id = Column(String(50), primary_key=True)
    name = Column(String(64), nullable=False)
    selection_mode = Column(String(10), nullable=False, default="MULTIPLE")
    status = Column(String(10), nullable=False, default="ACTIVE")
    sort_order = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_asset_tag_category_tenant_name"),)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "selection_mode": self.selection_mode,
                "status": self.status, "sort_order": self.sort_order}


class CreativeAssetTag(TenantMixin, Base):
    __tablename__ = "creative_asset_tags"

    id = Column(String(50), primary_key=True)
    name = Column(String(64), nullable=False)
    color = Column(String(20), nullable=True)
    category_id = Column(String(50), ForeignKey("creative_asset_tag_categories.id"), nullable=False)
    status = Column(String(10), nullable=False, default="ACTIVE")
    category = relationship("CreativeAssetTagCategory")

    __table_args__ = (
        UniqueConstraint("tenant_id", "category_id", "name", name="uq_asset_tags_tenant_category_name"),
        Index("ix_asset_tags_tenant_category_status", "tenant_id", "category_id", "status"),
    )

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color,
                "category_id": self.category_id, "status": self.status}
