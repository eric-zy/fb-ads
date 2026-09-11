from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship

from core.database import Base
from core.tenant import TenantMixin


creative_asset_tag_links = Table(
    "creative_asset_tag_links",
    Base.metadata,
    Column("asset_id", String(50), ForeignKey("creative_assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(50), ForeignKey("creative_asset_tags.id", ondelete="CASCADE"), primary_key=True),
)


class CreativeAssetTag(TenantMixin, Base):
    __tablename__ = "creative_asset_tags"

    id = Column(String(50), primary_key=True)
    name = Column(String(64), nullable=False)
    color = Column(String(20), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_creative_asset_tags_tenant_name"),)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color}
