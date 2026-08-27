from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, Enum, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from core.database import Base

class AccountStatus(str, enum.Enum):
    """账户状态"""
    ACTIVE = "active"
    FROZEN = "frozen"
    PAUSED = "paused"
    SUSPENDED = "suspended"

class AdAccount(Base):
    """Facebook广告账户模型"""
    __tablename__ = "ad_accounts"
    
    id = Column(String(50), primary_key=True, index=True)
    account_name = Column(String(255), nullable=False)
    account_id = Column(String(50), unique=True, nullable=False, index=True)
    
    # 账户信息
    currency = Column(String(10), default="USD")
    timezone = Column(String(50))
    status = Column(Enum(AccountStatus), default=AccountStatus.ACTIVE)
    
    # 花费统计
    total_spend = Column(Float, default=0.0)
    daily_spend_limit = Column(Float, nullable=False)
    monthly_spend_limit = Column(Float, nullable=False)
    
    # 风控标记
    is_frozen = Column(Boolean, default=False)
    frozen_reason = Column(String(500))
    frozen_at = Column(DateTime)
    unfreeze_at = Column(DateTime)
    
    # 风险评分
    risk_score = Column(Float, default=0.0)  # 0-1.0
    last_risk_check = Column(DateTime)
    
    # 关联数据
    campaigns = relationship("Campaign", back_populates="ad_account", cascade="all, delete-orphan")
    insights = relationship("AccountInsight", back_populates="ad_account", cascade="all, delete-orphan")
    risk_events = relationship("RiskEvent", back_populates="ad_account", cascade="all, delete-orphan")
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_account_id', 'account_id'),
        Index('ix_status_frozen', 'status', 'is_frozen'),
    )
    
    def __repr__(self):
        return f"<AdAccount {self.account_id} ({self.account_name})>"