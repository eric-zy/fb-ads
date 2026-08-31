"""审计日志写入工具（设计文档第 41.3 节）

记录：谁 / 什么时候 / 对哪个资源 / 做了什么 / 原参数与结果。

安全约定：
    写入前自动对常见敏感字段（Token / Secret / Password）做脱敏，
    避免明文凭据经审计日志落到数据库或备份里。
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from core.logger import logger
from models import AuditLog

# 出现这些关键字的字段值一律脱敏（不区分大小写，做包含匹配）
SENSITIVE_KEYS = (
    "token",
    "secret",
    "password",
    "access_key",
    "authorization",
)

MASKED_PLACEHOLDER = "***"


def _sanitize(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """递归脱敏：命中敏感键的字段值替换为占位符"""
    if not data:
        return data

    result: Dict[str, Any] = {}
    for key, value in data.items():
        key_lower = str(key).lower()
        if any(s in key_lower for s in SENSITIVE_KEYS):
            result[key] = MASKED_PLACEHOLDER if value else value
        elif isinstance(value, dict):
            result[key] = _sanitize(value)
        else:
            result[key] = value
    return result


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_data: Optional[Dict[str, Any]] = None,
    response_data: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
) -> Optional[AuditLog]:
    """写入一条审计日志

    审计失败不应影响主流程，因此内部异常只记录 error 日志后返回 None。

    Args:
        db: 数据库会话
        action: 动作，如 CREATE_CREDENTIAL / REVEAL_CREDENTIAL
        resource_type: 资源类型，如 credential / ad_account / meta_account
        resource_id: 资源 ID
        user_id: 操作人 ID
        request_data: 请求参数（自动脱敏）
        response_data: 执行结果
        request: FastAPI Request，用于记录来源 IP
    """
    ip_address = None
    if request is not None:
        ip_address = request.client.host if request.client else None

    try:
        log = AuditLog(
            id=uuid.uuid4().hex,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_data=_sanitize(request_data),
            response_data=_sanitize(response_data),
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
        return log
    except Exception as e:  # 审计失败不阻断业务
        logger.error(f"[audit] 写入审计日志失败: {type(e).__name__}: {e}")
        db.rollback()
        return None
