from datetime import datetime
from sqlalchemy import Column, DateTime, JSON, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from config.settings import settings

ConnectorBase = declarative_base()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class ConnectorCredential(ConnectorBase):
    __tablename__ = "connector_credentials"
    id = Column(String(50), primary_key=True)
    app_id = Column(String(128), nullable=False)
    access_token_encrypted = Column(Text, nullable=False)
    token_type = Column(String(32), default="USER", nullable=False)
    meta_user_id = Column(String(64), index=True)
    scopes = Column(JSON)
    expires_at = Column(DateTime)
    status = Column(String(32), default="ACTIVE", nullable=False, index=True)
    last_error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ConnectorMediaTask(ConnectorBase):
    __tablename__ = "connector_media_tasks"
    task_id = Column(String(50), primary_key=True)
    media_id = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="QUEUED")
    meta_asset_id = Column(String(128))
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ConnectorDeliveryTask(ConnectorBase):
    __tablename__ = "connector_delivery_tasks"
    task_id = Column(String(50), primary_key=True)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="QUEUED")
    step = Column(String(32), nullable=False, default="QUEUED")
    campaign_id = Column(String(128)); error_message = Column(Text)
    objects = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

def connector_session_factory():
    return SessionLocal()
