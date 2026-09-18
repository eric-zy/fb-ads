from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Index, Integer, String, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class CreativeAssetUsageAccountDailyStat(TenantMixin, Base):
    """素材按广告账户和日期拆分的可重算汇总。"""

    __tablename__ = "creative_asset_usage_account_daily_stats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_id", "ad_account_id", "stat_date", name="uq_asset_usage_account_daily_stat"),
        Index("ix_asset_usage_account_daily_tenant_date", "tenant_id", "stat_date"),
        Index("ix_asset_usage_account_daily_asset_date", "tenant_id", "asset_id", "stat_date"),
        Index("ix_asset_usage_account_daily_account_date", "tenant_id", "ad_account_id", "stat_date"),
    )

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(String(50), nullable=False, index=True)
    ad_account_id = Column(String(100), nullable=True, index=True)
    stat_date = Column(Date, nullable=False, index=True)
    usage_count = Column(Integer, nullable=False, default=0)
    successful_usage_count = Column(Integer, nullable=False, default=0)
    failed_usage_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
