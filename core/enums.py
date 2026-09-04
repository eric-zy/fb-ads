"""全局枚举与状态机定义

对齐设计文档：
- 第 18 节 Job 状态机
- 第 23 节 批量操作 Action 统一抽象
- 第 27 节 Meta 错误分类
"""
from enum import Enum


class JobStatus(str, Enum):
    """批量任务状态（设计文档第 18 节）

    PENDING → VALIDATING → QUEUED → RUNNING → SUCCESS / PARTIAL_SUCCESS / FAILED
    """
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobItemStatus(str, Enum):
    """单个账户维度的任务子项状态（设计文档原则三：每个账户独立状态）"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # 幂等命中，已存在则跳过


class ActionType(str, Enum):
    """批量操作类型（设计文档第 23 节）"""
    CREATE = "CREATE"
    PAUSE = "PAUSE"
    ENABLE = "ENABLE"
    UPDATE_BUDGET = "UPDATE_BUDGET"
    UPDATE_TARGETING = "UPDATE_TARGETING"
    SYNC = "SYNC"


class ErrorCategory(str, Enum):
    """Meta API 错误分类（设计文档第 27 节）"""
    AUTH = "AUTH"              # Token 过期 / 失效
    PERMISSION = "PERMISSION"  # 权限不足
    VALIDATION = "VALIDATION"  # 参数错误
    RATE_LIMIT = "RATE_LIMIT"  # 限流
    TEMPORARY = "TEMPORARY"    # 超时 / 5xx
    UNKNOWN = "UNKNOWN"


# 可重试错误：限流与临时错误延迟重试；参数/权限类直接失败（设计文档第 27 节处理策略）
RETRYABLE_CATEGORIES = frozenset({ErrorCategory.RATE_LIMIT, ErrorCategory.TEMPORARY})


def is_retryable(category: ErrorCategory) -> bool:
    """该错误类型是否值得重试"""
    return category in RETRYABLE_CATEGORIES


class TemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class CredentialStatus(str, Enum):
    """凭据状态（设计文档第 9 节：支持过期检测与权限异常标记）"""
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"   # 权限异常
    DISABLED = "DISABLED"
    VERIFYING = "VERIFYING"  # 正在校验中（异步校验场景）


class CredentialSource(str, Enum):
    """凭据来源

    MANUAL：管理员在后台手工粘贴 Token
    OAUTH ：通过 Meta OAuth 授权流程获取（可溯源到授权人与授权范围）
    """
    MANUAL = "MANUAL"
    OAUTH = "OAUTH"


class InstanceStatus(str, Enum):
    """投放实例状态（本地侧）"""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"
