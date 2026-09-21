from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Index

from core.database import Base
from core.tenant import TenantMixin


class MediaUploadSession(TenantMixin, Base):
    """OSS 上传会话；只记录上传协商和校验状态，不保存文件内容。"""

    __tablename__ = "media_upload_sessions"

    id = Column(String(50), primary_key=True, index=True)
    asset_id = Column(String(50), nullable=False, index=True)
    object_key = Column(String(1024), nullable=False)
    upload_id = Column(String(255), nullable=True, index=True, comment="OSS Multipart Upload ID")
    upload_mode = Column(String(20), nullable=False, default="single", comment="single/multipart")
    part_size = Column(Integer, nullable=True)
    part_count = Column(Integer, nullable=True)
    expected_size = Column(Integer, nullable=True)
    expected_md5 = Column(String(32), nullable=True)
    expected_sha256 = Column(String(64), nullable=True)
    status = Column(String(20), nullable=False, default="INIT", comment="INIT/UPLOADING/COMPLETED/EXPIRED/FAILED")
    error_message = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_media_upload_sessions_tenant_status", "tenant_id", "status"),
        Index("ix_media_upload_sessions_tenant_hash", "tenant_id", "expected_sha256", "expected_size"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "asset_id": self.asset_id,
            "object_key": self.object_key,
            "upload_id": self.upload_id,
            "upload_mode": self.upload_mode,
            "part_size": self.part_size,
            "part_count": self.part_count,
            "expected_size": self.expected_size,
            "expected_md5": self.expected_md5,
            "expected_sha256": self.expected_sha256,
            "status": self.status,
            "error_message": self.error_message,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
