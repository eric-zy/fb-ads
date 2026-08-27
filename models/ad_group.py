from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base

class AdGroup(Base):
    """广告组模型"""
    __tablename__ = "ad_groups"
    
    id = Column(String(50), primary_key=True, index=True)
    ad_group_id = Column(String(50), unique=True, nullable=False, index=True)
    campaign_id = Column(String(50), ForeignKey('campaigns.id'), nullable=False)
    
    # 基本信息
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="ACTIVE")
    
    # 定位与受众
    targeting = Column(String(500))  # JSON格式的定位信息
    audience_id = Column(String(100))
    
    # 竞价设置
    bid_amount = Column(Float)
    bid_strategy = Column(String(100))  # LOWEST_COST, TARGET_CPA等
    daily_budget = Column(Float)
    
    # 性能指标
    spend = Column(Float, default=0.0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    
    # 关联数据
    campaign = relationship("Campaign", back_populates="ad_groups")
    ads = relationship("Ad", back_populates="ad_group", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ad_group_id', 'ad_group_id'),
        Index('ix_campaign_id', 'campaign_id'),
    )
    
    def __repr__(self):
        return f"<AdGroup {self.ad_group_id} ({self.name})>"
