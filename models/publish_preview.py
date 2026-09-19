"""发布前预览快照。

预览不是一次普通的前端校验，而是提交时必须引用的、带过期时间的
服务端快照。这样可以避免用户在预览后修改账户、预算或素材配置，
再绕过预检直接创建任务。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, JSON, String, Text

from core.database import Base
from core.tenant import TenantMixin


class PublishPreview(TenantMixin, Base):
    __tablename__ = "publish_previews"

    id = Column(String(50), primary_key=True, index=True)
    created_by = Column(String(50), nullable=False, index=True)
    template_id = Column(String(50), nullable=True, index=True)
    source = Column(String(20), nullable=False, default="TEMPLATE")
    request_snapshot = Column(JSON, nullable=False)
    result_snapshot = Column(JSON, nullable=False)
    account_ids = Column(JSON, nullable=False, default=list)
    snapshot_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="READY")
    expires_at = Column(DateTime, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    submitted_job_id = Column(String(50), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_publish_previews_tenant_created", "tenant_id", "created_at"),
        Index("ix_publish_previews_tenant_status", "tenant_id", "status"),
    )

    def is_valid(self, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        return self.status == "READY" and self.expires_at > now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "created_by": self.created_by,
            "template_id": self.template_id,
            "source": self.source,
            "account_ids": self.account_ids or [],
            "snapshot_hash": self.snapshot_hash,
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "submitted_job_id": self.submitted_job_id,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "result": self.result_snapshot or {},
        }
