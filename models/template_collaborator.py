"""Campaign template collaboration access within a tenant."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import relationship

from core.database import Base
from core.tenant import TenantMixin


class TemplateCollaborator(TenantMixin, Base):
    """Explicit template access granted to another tenant member.

    Ownership remains on ``CampaignTemplate.created_by``.  This table only
    grants additional access and deliberately does not change account-level
    permissions.
    """

    __tablename__ = "template_collaborators"

    id = Column(String(50), primary_key=True, index=True)
    template_id = Column(String(50), ForeignKey("campaign_templates.id"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="VIEWER", server_default="VIEWER")
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    granted_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = relationship("CampaignTemplate", back_populates="collaborators")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("tenant_id", "template_id", "user_id", name="uq_template_collaborator"),
        Index("ix_template_collaborators_tenant_template_status", "tenant_id", "template_id", "status"),
        Index("ix_template_collaborators_tenant_user_status", "tenant_id", "user_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "template_id": self.template_id,
            "user_id": self.user_id,
            "role": self.role,
            "status": self.status,
            "granted_by": self.granted_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user": {
                "id": self.user.id,
                "username": self.user.username,
                "email": self.user.email,
            } if self.user else None,
        }
