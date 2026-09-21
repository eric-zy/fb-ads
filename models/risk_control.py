from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    resolved_by = Column(String(50))  # 处理人（详细审计信息写入 audit_logs）
    resolved_at = Column(DateTime)
    
    # 自动化处理
    auto_action_taken = Column(String(255))  # 自动执行的操作
    requires_manual_review = Column(Boolean, default=False)

    # 通知投递状态：事件本身可以持续未解决，但通知不能在每次任务重跑时重复发送。
    notification_status = Column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    notification_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    notification_sent_at = Column(DateTime)
    notification_error = Column(Text)
    notification_results = Column(JSON)
    
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

    # V1 可配置规则 DSL。
    # JSON 字段保持平台/租户规则的扩展能力，业务层负责校验具体条件结构。
    scope = Column(JSON, nullable=True, default=dict)  # account/campaign/adset/ad + ids
    conditions = Column(JSON, nullable=True, default=list)  # [{metric, operator, value, window}]
    logic = Column(String(8), nullable=False, default="AND", server_default="AND")

    # 阈值设置
    threshold = Column(Float)
    threshold_unit = Column(String(50))  # percentage, absolute, ratio等

    # 安全护栏：金额使用最小货币单位；时长/冷却使用秒。
    min_spend = Column(BigInteger, nullable=False, default=0, server_default="0")
    min_runtime = Column(Integer, nullable=False, default=0, server_default="0")
    cooldown_seconds = Column(Integer, nullable=False, default=0, server_default="0")
    max_actions_per_run = Column(Integer, nullable=False, default=100, server_default="100")
    dry_run = Column(Boolean, nullable=False, default=False, server_default="false")
    whitelist = Column(JSON, nullable=True, default=list)  # 明确跳过的账户/投放对象
    version = Column(Integer, nullable=False, default=1, server_default="1")
    
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

    def to_config(self) -> dict:
        """返回规则引擎使用的稳定配置结构。

        旧规则的 JSON 字段可能为 NULL，因此统一在边界处归一化，
        避免评估器在每个调用点重复处理兼容逻辑。
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "rule_type": self.rule_type,
            # SQLAlchemy applies scalar defaults on flush; legacy rows and
            # transient objects can still expose NULL before that point.
            "is_active": True if self.is_active is None else bool(self.is_active),
            "scope": self.scope or {},
            "conditions": self.conditions or [],
            "logic": (self.logic or "AND").upper(),
            "threshold": self.threshold,
            "threshold_unit": self.threshold_unit,
            "min_spend": int(self.min_spend or 0),
            "min_runtime": int(self.min_runtime or 0),
            "cooldown_seconds": int(self.cooldown_seconds or 0),
            "max_actions_per_run": int(self.max_actions_per_run or 100),
            "dry_run": bool(self.dry_run),
            "whitelist": self.whitelist or [],
            "priority": int(self.priority or 0),
            "version": int(self.version or 1),
        }


class RiskExecution(TenantMixin, Base):
    """规则评估/止损动作的独立执行记录。

    风险事件描述“发生了什么”，执行记录描述“规则如何命中、动作如何执行”。
    RC-02 先提供查询契约，RC-03/RC-04 再由规则引擎和 Celery 填充完整结果。
    """

    __tablename__ = "risk_executions"

    id = Column(String(50), primary_key=True, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    rule_id = Column(String(50), ForeignKey("risk_rules.id"), nullable=False, index=True)
    ad_account_id = Column(String(50), ForeignKey("ad_accounts.id"), nullable=False)
    target_type = Column(String(20), nullable=False)  # ACCOUNT / CAMPAIGN / ADSET / AD
    target_id = Column(String(128), nullable=False)
    rule_version = Column(Integer, nullable=False, default=1, server_default="1")
    mode = Column(String(20), nullable=False, default="LIVE", server_default="LIVE")
    status = Column(String(20), nullable=False, default="MATCHED", server_default="MATCHED")
    action = Column(String(32), nullable=False, default="ALERT", server_default="ALERT")

    matched_conditions = Column(JSON, nullable=True)
    metrics_snapshot = Column(JSON, nullable=True)
    idempotency_key = Column(String(160), nullable=False)
    provider_response = Column(JSON, nullable=True)
    error_code = Column(String(128))
    error_message = Column(Text)
    retry_count = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_risk_executions_tenant_created", "tenant_id", "created_at"),
        Index("ix_risk_executions_tenant_account", "tenant_id", "ad_account_id"),
        Index("ix_risk_executions_tenant_status", "tenant_id", "status"),
        Index("ix_risk_executions_tenant_rule", "tenant_id", "rule_id"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_risk_executions_tenant_idempotency",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "rule_id": self.rule_id,
            "ad_account_id": self.ad_account_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "rule_version": self.rule_version,
            "mode": self.mode,
            "status": self.status,
            "action": self.action,
            "matched_conditions": self.matched_conditions,
            "metrics_snapshot": self.metrics_snapshot,
            "idempotency_key": self.idempotency_key,
            "provider_response": self.provider_response,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
