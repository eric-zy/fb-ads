from sqlalchemy import Column, String, Float, Integer, DateTime, Boolean, Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from core.database import Base
from core.tenant import SharedTenantMixin, TenantMixin

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

class RiskEvent(TenantMixin, Base):
    """风险事件记录（租户级）"""
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
        Index('ix_risk_events_ad_account_id', 'ad_account_id'),
        Index('ix_risk_events_event_type', 'event_type'),
        Index('ix_risk_events_risk_level', 'risk_level'),
        Index('ix_risk_events_is_resolved', 'is_resolved'),
        # ---- 租户隔离复合索引 ----
        Index('ix_risk_events_tenant_account', 'tenant_id', 'ad_account_id'),
        Index('ix_risk_events_tenant_resolved', 'tenant_id', 'is_resolved'),
    )
    
    def __repr__(self):
        return f"<RiskEvent {self.event_type} - {self.risk_level}>"

class RiskRule(SharedTenantMixin, Base):
    """风控规则配置（平台内置 + 租户覆盖）

    `tenant_id IS NULL` → 平台内置规则，所有租户可见且不可修改
    `tenant_id = X`     → 租户 X 的自定义规则，仅 X 可见
    """
    __tablename__ = "risk_rules"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
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

    __table_args__ = (
        # 平台内置规则（tenant_id IS NULL）名称全局唯一
        Index(
            "uq_risk_rules_platform_name", "name", unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        # 租户自定义规则名称在租户内唯一
        Index(
            "uq_risk_rules_tenant_name", "tenant_id", "name", unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        # 单列索引由 SharedTenantMixin 的 index=True 提供（ix_risk_rules_tenant_id）
    )
    
    def __repr__(self):
        return f"<RiskRule {self.name} ({self.tenant_id or 'PLATFORM'})>"