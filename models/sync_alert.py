from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, Index
from core.database import Base
from core.tenant import TenantMixin


class SyncAlert(TenantMixin, Base):
    __tablename__ = "sync_alerts"
    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), nullable=True, index=True)
    alert_type = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    is_resolved = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_sync_alerts_tenant_open", "tenant_id", "is_resolved"),)

    def to_dict(self):
        return {"id": self.id, "ad_account_id": self.ad_account_id, "alert_type": self.alert_type,
                "title": self.title, "message": self.message, "is_resolved": self.is_resolved,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None}
