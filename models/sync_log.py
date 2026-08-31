"""Meta 同步日志（文档 §10）

与 `audit_logs` 职责分离，**不要混用**：

    meta_sync_logs  → 记录"同步任务"的执行结果（拉了哪些、成功多少、失败原因）
    audit_logs      → 记录"人的操作"审计（谁改了什么）

同步日志是排障依据：账户池不准时先看这里，而不是去翻操作审计。
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from datetime import datetime
import enum

from core.database import Base


class SyncType(str, enum.Enum):
    """同步类型（文档 §10）"""

    BUSINESS = "BUSINESS"        # 只同步 BM 基础信息
    AD_ACCOUNT = "AD_ACCOUNT"    # 只同步 BM 下的广告账户
    FULL = "FULL"                # BM + 广告账户全量


class SyncLogStatus(str, enum.Enum):
    """同步任务状态（文档 §10）"""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class MetaSyncLog(Base):
    """Meta 同步日志"""

    __tablename__ = "meta_sync_logs"

    id = Column(String(50), primary_key=True, index=True)

    business_id = Column(
        String(50),
        ForeignKey("meta_accounts.id"),
        nullable=True,
        index=True,
        comment="对应 BM；BM 被删除时置空而非级联删除日志",
    )

    sync_type = Column(String(32), nullable=False, comment="BUSINESS / AD_ACCOUNT / FULL")
    status = Column(
        String(32),
        default=SyncLogStatus.RUNNING.value,
        nullable=False,
        comment="RUNNING / SUCCESS / PARTIAL_SUCCESS / FAILED",
    )

    total_count = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)

    error_message = Column(Text, comment="错误信息")
    error_detail = Column(Text, comment="逐条失败明细（JSON 字符串）")

    # 异步化（文档 §25）：HTTP 只返回 job_id，由 Celery 执行
    celery_task_id = Column(String(64), index=True, comment="Celery 任务 ID，便于追踪")

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, comment="完成时间，为空表示仍在执行")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "business_id": self.business_id,
            "sync_type": self.sync_type,
            "status": self.status,
            "total_count": self.total_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "error_message": self.error_message,
            "error_detail": self.error_detail,
            "celery_task_id": self.celery_task_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<MetaSyncLog {self.sync_type} {self.status} ({self.success_count}/{self.total_count})>"
