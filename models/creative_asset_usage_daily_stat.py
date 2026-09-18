from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, String, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class CreativeAssetUsageDailyStat(TenantMixin, Base):
    """素材使用事件的按日可重算汇总。"""

    __tablename__ = "creative_asset_usage_daily_stats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_id", "stat_date", name="uq_asset_usage_daily_stat"),
        Index("ix_asset_usage_daily_stats_tenant_date", "tenant_id", "stat_date"),
        Index("ix_asset_usage_daily_stats_tenant_asset_date", "tenant_id", "asset_id", "stat_date"),
    )

    id = Column(String(150), primary_key=True, index=True)
    asset_id = Column(String(50), nullable=False, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    usage_count = Column(Integer, nullable=False, default=0)
    successful_usage_count = Column(Integer, nullable=False, default=0)
    failed_usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "date": self.stat_date.isoformat() if self.stat_date else None,
            "usage_count": self.usage_count,
            "successful_usage_count": self.successful_usage_count,
            "failed_usage_count": self.failed_usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }
