from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint
from core.database import Base

class ConnectorInsightsSnapshot(Base):
    __tablename__ = "connector_insights_snapshots"
    id = Column(String(50), primary_key=True)
    request_id = Column(String(64), nullable=False)
    credential_id = Column(String(50), nullable=False)
    account_id = Column(String(64), nullable=False)
    days = Column(Integer, nullable=False)
    items = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("request_id", name="uq_connector_insights_request"),)
