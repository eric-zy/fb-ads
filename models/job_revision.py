"""投放任务修订草稿。

原 CampaignJob 是不可变执行记录；本模型保存编辑中的配置和预检结果，
避免用户刷新页面后丢失修复内容，也为版本审计提供稳定载体。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from core.database import Base
from core.tenant import TenantMixin


class CampaignJobRevision(TenantMixin, Base):
    __tablename__ = "campaign_job_revisions"

    id = Column(String(50), primary_key=True, index=True)
    base_job_id = Column(String(50), ForeignKey("campaign_jobs.id"), nullable=False, index=True)
    published_job_id = Column(String(50), ForeignKey("campaign_jobs.id"), nullable=True, index=True)
    template_id = Column(String(50), ForeignKey("campaign_templates.id"), nullable=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="DRAFT")
    source = Column(String(32), nullable=True)
    account_ids = Column(JSON, nullable=True)
    snapshot = Column(JSON, nullable=True)
    diff = Column(JSON, nullable=True)
    validation_result = Column(JSON, nullable=True)
    edit_reason = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    base_job = relationship("CampaignJob", foreign_keys=[base_job_id], back_populates="draft_revisions")
    published_job = relationship("CampaignJob", foreign_keys=[published_job_id])

    __table_args__ = (
        UniqueConstraint("base_job_id", "version", name="uq_job_revision_version"),
        Index("ix_job_revisions_tenant_status", "tenant_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "base_job_id": self.base_job_id,
            "published_job_id": self.published_job_id,
            "template_id": self.template_id,
            "version": self.version,
            "status": self.status,
            "source": self.source,
            "account_ids": self.account_ids or [],
            "snapshot": self.snapshot,
            "diff": self.diff or [],
            "validation_result": self.validation_result,
            "edit_reason": self.edit_reason,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
