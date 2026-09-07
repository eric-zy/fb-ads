from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, Index
from core.database import Base
from core.tenant import TenantMixin

class AsyncTaskRecord(TenantMixin, Base):
    __tablename__ = "async_task_records"
    task_id = Column(String(100), primary_key=True)
    task_type = Column(String(64), nullable=False)
    object_type = Column(String(32), nullable=True)
    object_ids = Column(JSON, nullable=True)
    status = Column(String(32), default="PENDING", nullable=False)
    result_summary = Column(JSON, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_async_task_records_tenant_created", "tenant_id", "created_at"),)

    def to_dict(self):
        return {"task_id": self.task_id, "task_type": self.task_type, "object_type": self.object_type, "object_ids": self.object_ids, "status": self.status, "result_summary": self.result_summary, "created_by": self.created_by, "created_at": self.created_at.isoformat() if self.created_at else None, "finished_at": self.finished_at.isoformat() if self.finished_at else None}
