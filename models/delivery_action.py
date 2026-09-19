"""已发布对象的异步操作记录。"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, JSON, String, Text

from core.database import Base
from core.tenant import TenantMixin


class DeliveryAction(TenantMixin, Base):
    __tablename__ = "delivery_actions"

    id = Column(String(50), primary_key=True, index=True)
    object_type = Column(String(20), nullable=False)  # CAMPAIGN / ADSET / AD
    object_id = Column(String(50), nullable=False, index=True)
    account_id = Column(String(50), nullable=False, index=True)
    action = Column(String(20), nullable=False)  # PAUSE / ENABLE / ARCHIVE
    requested_by = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="REQUESTED")
    idempotency_key = Column(String(128), nullable=False, unique=True)
    before_status = Column(String(32), nullable=True)
    desired_status = Column(String(32), nullable=True)
    remote_status = Column(String(32), nullable=True)
    task_id = Column(String(64), nullable=True, index=True)
    request_payload = Column(JSON, nullable=True)
    result_payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_delivery_actions_tenant_object", "tenant_id", "object_type", "object_id"),
        Index("ix_delivery_actions_tenant_created", "tenant_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "account_id": self.account_id,
            "action": self.action,
            "requested_by": self.requested_by,
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "before_status": self.before_status,
            "desired_status": self.desired_status,
            "remote_status": self.remote_status,
            "task_id": self.task_id,
            "result_payload": self.result_payload,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
