from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, JSON, String, UniqueConstraint
from core.database import Base
from core.tenant import TenantMixin

class ConnectorInsightsSnapshot(TenantMixin, Base):
    """Connector 原始报表快照。

    回调没有 SaaS JWT，租户由 account_id 反查后显式建立；仍保留租户键，
    避免该表未来被报表或运维接口读取时变成跨租户数据源。
    """

    __tablename__ = "connector_insights_snapshots"
    id = Column(String(50), primary_key=True)
    request_id = Column(String(64), nullable=False)
    credential_id = Column(String(50), nullable=False)
    account_id = Column(String(64), nullable=False)
    days = Column(Integer, nullable=False)
    items = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("request_id", name="uq_connector_insights_request"),)
