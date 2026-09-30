from datetime import datetime
from sqlalchemy import Column, DateTime, JSON, String, Index, UniqueConstraint
from core.database import Base
from core.tenant import TenantMixin


class AccountAssignmentRule(TenantMixin, Base):
    __tablename__ = "account_assignment_rules"
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    priority = Column(String(20), default="100", nullable=False)
    rule_type = Column(String(32), nullable=False, default="ROUND_ROBIN")
    rule_config = Column(JSON, default=dict)
    target_user_id = Column(String(50), nullable=True, index=True)
    status = Column(String(20), default="ACTIVE", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (Index("ix_assignment_rules_tenant_status", "tenant_id", "status"),)


class AccountAssignmentLog(TenantMixin, Base):
    __tablename__ = "account_assignment_logs"
    id = Column(String(50), primary_key=True, index=True)
    account_id = Column(String(50), nullable=False, index=True)
    from_user_id = Column(String(50), nullable=True)
    to_user_id = Column(String(50), nullable=True)
    rule_id = Column(String(50), nullable=True)
    action = Column(String(32), nullable=False)
    operator_id = Column(String(50), nullable=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccountOperationLease(TenantMixin, Base):
    """账户关键操作的短时协调租约。

    实际投放任务仍由 worker 层的 Redis 锁保护；本表用于 API/UI 层提示并发
    操作冲突，避免多个投手同时编辑或提交同一广告账户。
    """

    __tablename__ = "account_operation_leases"

    id = Column(String(50), primary_key=True, index=True)
    account_id = Column(String(50), nullable=False, index=True)
    holder_user_id = Column(String(50), nullable=False, index=True)
    operation_type = Column(String(50), nullable=False)
    lease_token = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "account_id", name="uq_account_operation_lease_account"
        ),
        Index(
            "ix_account_operation_lease_active",
            "tenant_id",
            "account_id",
            "expires_at",
        ),
    )
