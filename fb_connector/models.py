from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text, create_engine
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
    # 保存完整入参，Worker 重启后才能恢复丢失的 Celery 消息。
    credential_id = Column(String(50))
    account_id = Column(String(64))
    asset_type = Column(String(16))
    source_url = Column(Text)
    status = Column(String(32), nullable=False, default="QUEUED")
    phase = Column(String(32), nullable=True, default="QUEUED")
    total_bytes = Column(Integer, nullable=True)
    uploaded_bytes = Column(Integer, nullable=True, default=0)
    upload_session_id = Column(String(128), nullable=True)
    meta_video_id = Column(String(128), nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    meta_asset_id = Column(String(128))
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ConnectorDeliveryTask(ConnectorBase):
    __tablename__ = "connector_delivery_tasks"
    task_id = Column(String(50), primary_key=True)
    idempotency_key = Column(String(128), nullable=False, unique=True)
    source_task_id = Column(String(64))
    credential_id = Column(String(50))
    account_id = Column(String(64))
    request_payload = Column(JSON)
    status = Column(String(32), nullable=False, default="QUEUED")
    step = Column(String(32), nullable=False, default="QUEUED")
    campaign_id = Column(String(128)); error_message = Column(Text)
    objects = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ConnectorCallbackEvent(ConnectorBase):
    """Connector → SaaS 的可靠回调事件 outbox。"""

    __tablename__ = "connector_callback_events"

    event_id = Column(String(64), primary_key=True)
    task_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    callback_path = Column(String(255), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)

def connector_session_factory():
    return SessionLocal()
