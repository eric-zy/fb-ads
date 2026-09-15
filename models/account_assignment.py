from datetime import datetime
from sqlalchemy import Column, DateTime, JSON, String, Index
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
