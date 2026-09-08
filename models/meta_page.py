"""租户隔离的 Facebook Page 资产。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint

from core.database import Base
from core.enums import CredentialStatus
from core.security import decrypt_token, encrypt_token, mask_token
from core.tenant import TenantMixin


class MetaPage(TenantMixin, Base):
    __tablename__ = "meta_pages"

    id = Column(String(50), primary_key=True, index=True)
    page_id = Column(String(64), nullable=False)
    page_name = Column(String(255), nullable=False)
    category = Column(String(255))
    tasks = Column(JSON)
    credential_id = Column(String(50), nullable=False, index=True)
    connection_id = Column(
        String(50), ForeignKey("meta_connections.id"), nullable=True, index=True,
        comment="所属 Meta OAuth 授权连接",
    )
    page_access_token_encrypted = Column(Text, nullable=False)
    status = Column(String(32), default=CredentialStatus.ACTIVE.value, nullable=False)
    last_error = Column(Text)
    last_synced_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "page_id", name="uq_meta_pages_tenant_page"),
        Index("ix_meta_pages_tenant_status", "tenant_id", "status"),
        Index("ix_meta_pages_tenant_credential", "tenant_id", "credential_id"),
    )

    def set_page_access_token(self, token: str) -> None:
        self.page_access_token_encrypted = encrypt_token(token)

    def get_page_access_token(self) -> str:
        return decrypt_token(self.page_access_token_encrypted)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "category": self.category,
            "tasks": self.tasks or [],
            "credential_id": self.credential_id,
            "connection_id": self.connection_id,
            "status": self.status,
            "last_error": self.last_error,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "page_access_token_masked": mask_token(self.get_page_access_token()),
        }
