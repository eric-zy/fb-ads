from sqlalchemy import Column, String, Float, Integer, DateTime, Date, ForeignKey, Index, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, date
from core.database import Base

class AccountInsight(Base):
    """账户级别的数据洞察"""
    __tablename__ = "account_insights"
    
    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), ForeignKey('ad_accounts.id'), nullable=False)
    
    # 日期
    date = Column(Date, nullable=False, index=True)
    
    # KPI指标
    spend = Column(Float, default=0.0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    
    # 计算指标
    ctr = Column(Float, default=0.0)  # 点击率
    cpc = Column(Float, default=0.0)  # 每次点击成本
    cpm = Column(Float, default=0.0)  # 千次展示成本
    roas = Column(Float, default=0.0) # 广告支出回报率
    
    # 趋势指标
    spend_trend = Column(Float, default=0.0)  # 与前一天的增长率
    conversion_trend = Column(Float, default=0.0)
    
    # 额外属性
    extra_data = Column(JSON)  # 存储其他指标
    
    ad_account = relationship("AdAccount", back_populates="insights")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_account_date', 'ad_account_id', 'date'),
        Index('ix_date', 'date'),
    )

class CampaignInsight(Base):
    """系列级别的数据洞察"""
    __tablename__ = "campaign_insights"
    
    id = Column(String(50), primary_key=True, index=True)
    campaign_id = Column(String(50), ForeignKey('campaigns.id'), nullable=False)
    
    date = Column(Date, nullable=False, index=True)
    
    # KPI指标
    spend = Column(Float, default=0.0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    
    # 计算指标
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    cpm = Column(Float, default=0.0)
    roas = Column(Float, default=0.0)
    
    campaign = relationship("Campaign", back_populates="insights")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_campaign_date', 'campaign_id', 'date'),
    )

class AdInsight(Base):
    """广告级别的数据洞察"""
    __tablename__ = "ad_insights"
    
    id = Column(String(50), primary_key=True, index=True)
    ad_id = Column(String(50), ForeignKey('ads.id'), nullable=False)
    
    date = Column(Date, nullable=False, index=True)
    
    # KPI指标
    spend = Column(Float, default=0.0)
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    
    # 计算指标
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    cpm = Column(Float, default=0.0)
    
    ad = relationship("Ad", back_populates="insights")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ad_date', 'ad_id', 'date'),
    )
