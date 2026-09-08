"""Meta OAuth 授权连接：一个租户下一个 Meta 用户的一次授权。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, JSON, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class MetaConnection(TenantMixin, Base):
    __tablename__ = "meta_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "meta_user_id", "app_id", name="uq_meta_connections_user_app"),
        Index("ix_meta_connections_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    meta_user_id = Column(String(64), nullable=False, index=True)
    app_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    scopes = Column(JSON)
    authorized_by_user_id = Column(String(50))
    expires_at = Column(DateTime)
    last_synced_at = Column(DateTime)
    last_error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "meta_user_id": self.meta_user_id,
            "app_id": self.app_id,
            "status": self.status,
            "scopes": self.scopes or [],
            "authorized_by_user_id": self.authorized_by_user_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
