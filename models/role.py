"""租户级角色与权限模板。"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Index, JSON, String, Text, UniqueConstraint
from core.database import Base
from core.tenant import TenantMixin


class Role(TenantMixin, Base):
    __tablename__ = "roles"
    id = Column(String(50), primary_key=True, index=True)
    code = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    permissions = Column(JSON, nullable=False, default=list)
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),
        Index("ix_roles_tenant_created", "tenant_id", "created_at"),
    )

    def to_dict(self):
        return {"id": self.id, "tenant_id": self.tenant_id, "code": self.code,
                "name": self.name, "description": self.description,
                "permissions": self.permissions or [], "is_system": self.is_system,
                "created_at": self.created_at.isoformat() if self.created_at else None}
