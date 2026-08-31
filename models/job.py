from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from core.database import Base
from core.enums import ActionType, ErrorCategory, JobItemStatus, JobStatus


class CampaignJob(Base):
    """批量投放任务（设计文档第 17.1 节 / Job Center）

    一次批量操作 = 一个 Job，下挂 N 个 JobItem（每个广告账户一个）。
    支持部分成功：100 个账户成功 93 个时，Job 状态为 PARTIAL_SUCCESS，
    用户可只重跑失败的 7 个（设计文档第 30 节）。
    """

    __tablename__ = "campaign_jobs"

    id = Column(String(50), primary_key=True, index=True)
    template_id = Column(String(50), ForeignKey("campaign_templates.id"), nullable=True, index=True)

    action_type = Column(String(32), default=ActionType.CREATE.value,
                         comment="CREATE / PAUSE / ENABLE / UPDATE_BUDGET / SYNC")
    status = Column(String(32), default=JobStatus.PENDING.value, index=True)

    total_accounts = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # 批量操作的覆盖参数，如 {"budget_override": 100, "status": "PAUSED"}
    params = Column(JSON)

    created_by = Column(String(50), comment="操作人 user_id")
    error_message = Column(Text, comment="Job 级失败原因")

    # ---- 定时执行支持 ----
    # scheduled_at 为空表示立即执行；非空则由 Celery 按 eta 延迟派发。
    scheduled_at = Column(DateTime, nullable=True, index=True, comment="计划执行时间（UTC），为空表示立即执行")
    # 记录 Celery 编排任务的 ID，取消定时任务时用于 revoke
    celery_task_id = Column(String(64), nullable=True, comment="Celery 编排任务 ID，用于撤销定时任务")

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    template = relationship("CampaignTemplate", back_populates="jobs")
    items = relationship("CampaignJobItem", back_populates="job", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "action_type": self.action_type,
            "status": self.status,
            "total_accounts": self.total_accounts,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "params": self.params,
            "created_by": self.created_by,
            "error_message": self.error_message,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "celery_task_id": self.celery_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class CampaignJobItem(Base):
    """批量任务的单个账户子项（设计文档第 17.2 节）

    原则三：每个账户独立状态，100 个账户不是一个状态。
    原则四：幂等 —— 通过 request_hash 标识同一次操作，
            重复提交/重试不会导致重复创建（设计文档第 29 节）。
    """

    __tablename__ = "campaign_job_items"
    __table_args__ = (
        # 同一 Job 内同一账户只允许一条子项
        UniqueConstraint("job_id", "ad_account_id", name="uq_job_account"),
        Index("ix_job_items_request_hash", "request_hash"),
    )

    id = Column(String(50), primary_key=True, index=True)
    job_id = Column(String(50), ForeignKey("campaign_jobs.id"), nullable=False, index=True)
    ad_account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False, index=True)

    status = Column(String(32), default=JobItemStatus.PENDING.value, index=True)

    # 创建成功后回写的 Meta 对象 ID
    campaign_instance_id = Column(String(50), ForeignKey("campaign_instances.id"), nullable=True)
    meta_campaign_id = Column(String(128))
    adset_ids = Column(JSON, comment="Meta AdSet ID 列表")
    ad_ids = Column(JSON, comment="Meta Ad ID 列表")

    # 请求/响应留痕，便于排查与审计
    request_payload = Column(JSON)
    response_payload = Column(JSON)

    # 幂等键：由 (template_id, ad_account_id, action_type, 关键参数) 计算
    request_hash = Column(String(64), index=True, comment="幂等哈希，防止重复创建")

    error_code = Column(String(128))
    error_message = Column(Text)
    error_category = Column(String(32), comment="AUTH / PERMISSION / VALIDATION / RATE_LIMIT / TEMPORARY / UNKNOWN")

    retry_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("CampaignJob", back_populates="items")
    ad_account = relationship("AdAccount")
    campaign_instance = relationship("CampaignInstance")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "ad_account_id": self.ad_account_id,
            "status": self.status,
            "meta_campaign_id": self.meta_campaign_id,
            "adset_ids": self.adset_ids,
            "ad_ids": self.ad_ids,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "error_category": self.error_category,
            "retry_count": self.retry_count,
            "request_hash": self.request_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def mark_failed(self, code: str = None, message: str = None,
                    category: ErrorCategory = ErrorCategory.UNKNOWN) -> None:
        """统一失败落库，避免各调用点自行拼装错误字段"""
        self.status = JobItemStatus.FAILED.value
        self.error_code = code
        self.error_message = message
        self.error_category = category.value if isinstance(category, ErrorCategory) else category
