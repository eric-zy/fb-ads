from sqlalchemy import Column, String, DateTime, Text, JSON, Index
from datetime import datetime

from core.database import Base
from core.tenant import TenantMixin


class AuditLog(TenantMixin, Base):
    """审计日志（设计文档第 41.3 节）

    记录：谁 / 什么时候 / 对哪个资源 / 做了什么 / 原参数与结果。

    多租户：`tenant_id` 为 NULL 表示**平台级操作**（如创建租户、平台管理员
    跨租户操作），租户成员看不到；租户内操作则只对本租户可见。
    平台运营查看全量日志时需 `bypass_tenant()`。
    """

    __tablename__ = "audit_logs"
    __tenant_nullable__ = True

    id = Column(String(50), primary_key=True, index=True)

    user_id = Column(String(50), index=True, comment="操作人")
    action = Column(String(64), index=True, comment="动作，如 CREATE_JOB / UPDATE_BUDGET")
    resource_type = Column(String(64), comment="资源类型，如 campaign_job / ad_account")
    resource_id = Column(String(128), index=True, comment="资源 ID")

    request_data = Column(JSON, comment="请求参数（敏感字段需脱敏后写入）")
    response_data = Column(JSON, comment="执行结果")

    ip_address = Column(String(64))

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        # 审计日志量级大：租户内按 (租户, 时间) / (租户, 资源) 检索
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_logs_tenant_resource", "tenant_id", "resource_type", "resource_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "request_data": self.request_data,
            "response_data": self.response_data,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
