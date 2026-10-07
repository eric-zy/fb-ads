"""Auditable report windows; an empty complete response is still a snapshot."""
from datetime import datetime
from sqlalchemy import Column, String, Date, DateTime, JSON, ForeignKey, Index
from core.database import Base
from core.tenant import TenantMixin


class ReportSyncRun(TenantMixin, Base):
    __tablename__ = "report_sync_runs"
    id = Column(String(50), primary_key=True)
    account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False)
    task_id = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="RUNNING")
    snapshots = Column(JSON, nullable=True)
    error = Column(String(2000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    __table_args__ = (Index("ix_report_sync_runs_account_finished", "account_id", "finished_at"),)
