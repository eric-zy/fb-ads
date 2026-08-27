from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, Enum, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from core.database import Base

class RiskLevel(str, enum.Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RiskEventType(str, enum.Enum):
    """风险事件类型"""
    UNUSUAL_SPEND = "unusual_spend"  # 异常花费
    LOW_QUALITY = "low_quality"      # 低质量广告
    HIGH_FRAUD = "high_fraud"        # 高欺诈风险
    ACCOUNT_FROZEN = "account_frozen" # 账户冻结
    POLICY_VIOLATION = "policy_violation" # 政策违规
    SUSPICIOUS_PATTERN = "suspicious_pattern" # 可疑模式

class RiskEvent(Base):
    """风险事件记录"""
    __tablename__ = "risk_events"
    
    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), ForeignKey('ad_accounts.id'), nullable=False)
    
    event_type = Column(Enum(RiskEventType), nullable=False)
    risk_level = Column(Enum(RiskLevel), nullable=False)
    risk_score = Column(Float, default=0.0)
    
    # 风险描述
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # 相关数据
    related_campaign_id = Column(String(50))
    related_ad_id = Column(String(50))
    
    # 处理状态
    is_resolved = Column(Boolean, default=False)
    resolution = Column(Text)  # 处理方案
    resolved_at = Column(DateTime)
    
    # 自动化处理
    auto_action_taken = Column(String(255))  # 自动执行的操作
    requires_manual_review = Column(Boolean, default=False)
    
    # 关联数据
    ad_account = relationship("AdAccount", back_populates="risk_events")
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_ad_account_id', 'ad_account_id'),
        Index('ix_event_type', 'event_type'),
        Index('ix_risk_level', 'risk_level'),
        Index('ix_is_resolved', 'is_resolved'),
    )
    
    def __repr__(self):
        return f"<RiskEvent {self.event_type} - {self.risk_level}>"

class RiskRule(Base):
    """风控规则配置"""
    __tablename__ = "risk_rules"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    
    # 规则配置
    rule_type = Column(String(100), nullable=False)  # spend_anomaly, quality_score, fraud_detection等
    is_active = Column(Boolean, default=True)
    
    # 阈值设置
    threshold = Column(Float)
    threshold_unit = Column(String(50))  # percentage, absolute, ratio等
    
    # 处理方案
    action_on_trigger = Column(String(255))  # pause_campaign, freeze_account, alert等
    alert_channels = Column(String(500))  # email, dingtalk, slack
    
    priority = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<RiskRule {self.name}>"