from sqlalchemy import BigInteger, Column, String, Float, Integer, DateTime, Boolean, ForeignKey, Text, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from core.database import Base
from core.tenant import TenantMixin

class Ad(TenantMixin, Base):
    """广告模型"""
    __tablename__ = "ads"
    
    id = Column(String(50), primary_key=True, index=True)
    ad_id = Column(String(50), unique=True, nullable=False)
    ad_group_id = Column(String(50), ForeignKey('ad_groups.id'), nullable=False)
    
    # 基本信息
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="ACTIVE")  # ACTIVE, PAUSED, DELETED
    creative_id = Column(String(100))
    
    # 文案与素材
    headline = Column(String(255))
    description = Column(Text)
    body = Column(Text)
    image_url = Column(String(500))
    video_url = Column(String(500))
    
    # 性能指标
    spend = Column(BigInteger, default=0, comment="花费（最小货币单位）")
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    cpc = Column(Float, default=0.0)
    cpm = Column(Float, default=0.0)
    conversion_rate = Column(Float, default=0.0)
    
    # 风控标记
    quality_score = Column(Float, default=0.0)  # 广告质量分
    is_low_quality = Column(Boolean, default=False)
    fraud_score = Column(Float, default=0.0)  # 欺诈评分
    
    # 关联数据
    ad_group = relationship("AdGroup", back_populates="ads")
    insights = relationship("AdInsight", back_populates="ad", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ads_ad_id', 'ad_id'),
        Index('ix_ads_ad_group_id', 'ad_group_id'),
        Index('ix_ads_status', 'status'),
        # ---- 租户隔离复合索引 ----
        Index('ix_ads_tenant_group', 'tenant_id', 'ad_group_id'),
        Index('ix_ads_tenant_status', 'tenant_id', 'status'),
    )
    
    def __repr__(self):
        return f"<Ad {self.ad_id} ({self.name})>"