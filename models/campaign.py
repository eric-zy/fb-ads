from sqlalchemy import BigInteger, Column, String, Float, Integer, DateTime, Boolean, Enum, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from core.database import Base

class CampaignStatus(str, enum.Enum):
    """系列状态"""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"

class Campaign(Base):
    """广告系列模型"""
    __tablename__ = "campaigns"
    
    id = Column(String(50), primary_key=True, index=True)
    campaign_id = Column(String(50), unique=True, nullable=False)
    ad_account_id = Column(String(50), ForeignKey('ad_accounts.id'), nullable=False)
    
    # 基本信息
    name = Column(String(255), nullable=False)
    objective = Column(String(100))  # REACH, ENGAGEMENT, CONVERSIONS等
    status = Column(Enum(CampaignStatus), default=CampaignStatus.ACTIVE)
    
    # 预算与时间（金额一律最小货币单位，见 core/money.py）
    budget = Column(BigInteger, comment="总预算（最小货币单位）")
    daily_budget = Column(BigInteger, comment="日预算（最小货币单位）")
    start_time = Column(DateTime)
    stop_time = Column(DateTime)
    
    # 性能指标
    spend = Column(BigInteger, default=0, comment="花费（最小货币单位）")
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)  # 点击率
    cpc = Column(Float, default=0.0)  # 每次点击成本
    cpm = Column(Float, default=0.0)  # 千次展示成本
    
    # 风控相关
    risk_score = Column(Float, default=0.0)
    is_flagged = Column(Boolean, default=False)  # 是否被标记为风险
    
    # 关联数据
    ad_account = relationship("AdAccount", back_populates="campaigns")
    ad_groups = relationship("AdGroup", back_populates="campaign", cascade="all, delete-orphan")
    insights = relationship("CampaignInsight", back_populates="campaign", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_campaigns_campaign_id', 'campaign_id'),
        Index('ix_campaigns_ad_account_id', 'ad_account_id'),
        Index('ix_campaigns_status', 'status'),
    )
    
    def __repr__(self):
        return f"<Campaign {self.campaign_id} ({self.name})>"