from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class MetaInstagramSnapshot(TenantMixin, Base):
    """账户级 Instagram 身份及 Page 关联快照；空列表也是有效同步结果。"""

    __tablename__ = "meta_instagram_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ad_account_id", name="uq_instagram_tenant_account"),
        Index("ix_instagram_tenant_account", "tenant_id", "ad_account_id"),
    )
    id = Column(String(50), primary_key=True)
    ad_account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False)
    credential_id = Column(String(50), nullable=False)
    items = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="HEALTHY")
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
