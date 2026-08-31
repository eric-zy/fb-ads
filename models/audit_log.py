from sqlalchemy import Column, String, DateTime, Text, JSON
from datetime import datetime

from core.database import Base


class AuditLog(Base):
    """审计日志（设计文档第 41.3 节）

    记录：谁 / 什么时候 / 对哪个资源 / 做了什么 / 原参数与结果。
    """

    __tablename__ = "audit_logs"

    id = Column(String(50), primary_key=True, index=True)

    user_id = Column(String(50), index=True, comment="操作人")
    action = Column(String(64), index=True, comment="动作，如 CREATE_JOB / UPDATE_BUDGET")
    resource_type = Column(String(64), comment="资源类型，如 campaign_job / ad_account")
    resource_id = Column(String(128), index=True, comment="资源 ID")

    request_data = Column(JSON, comment="请求参数（敏感字段需脱敏后写入）")
    response_data = Column(JSON, comment="执行结果")

    ip_address = Column(String(64))

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "request_data": self.request_data,
            "response_data": self.response_data,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
