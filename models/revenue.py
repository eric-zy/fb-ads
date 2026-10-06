from datetime import datetime
from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from core.database import Base
from core.tenant import TenantMixin


class RevenueDailyTotal(TenantMixin, Base):
    """Daily source totals replace previous imports; separate sources are additive."""
    __tablename__ = "revenue_daily_totals"
    id = Column(String(50), primary_key=True)
    ad_account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False)
    date = Column(Date, nullable=False)
    source = Column(String(64), nullable=False)
    currency = Column(String(16), nullable=False)
    revenue = Column(BigInteger, nullable=False)
    updated_by = Column(String(50), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "ad_account_id", "date", "source", name="uq_revenue_daily_source"),
        Index("ix_revenue_daily_tenant_account_date", "tenant_id", "ad_account_id", "date"),
    )
