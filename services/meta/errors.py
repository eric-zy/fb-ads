"""Meta API 错误分类（设计文档第 27 节）

设计文档明确反对：
    except Exception:
        print("error")

要求按 AUTH / PERMISSION / VALIDATION / RATE_LIMIT / TEMPORARY / UNKNOWN 分类，
不同分类对应不同处理策略：

    RATE_LIMIT  → 延迟 + Retry
    TEMPORARY   → Retry
    VALIDATION  → 直接失败（重试无意义）
    PERMISSION  → 账户/凭据标记异常，不重试
    AUTH        → 凭据失效，需更换 Token
"""
from typing import Optional

from core.enums import ErrorCategory, is_retryable

try:  # SDK 不可用时仍可导入本模块（便于单测）
    from facebook_business.exceptions import FacebookRequestError
except ImportError:  # pragma: no cover
    FacebookRequestError = None


class MetaApiError(Exception):
    """Meta API 调用失败的统一异常

    业务层只需捕获这一种异常，通过 category 决定处理策略。
    """

    def __init__(
        self,
        message: str,
        *,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        code: Optional[int] = None,
        subcode: Optional[int] = None,
        http_status: Optional[int] = None,
        fbtrace_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.code = code
        self.subcode = subcode
        self.http_status = http_status
        self.fbtrace_id = fbtrace_id

    @property
    def retryable(self) -> bool:
        """该错误是否值得重试"""
        return is_retryable(self.category)

    def __str__(self) -> str:
        parts = [f"[{self.category.value}] {self.message}"]
        if self.code is not None:
            parts.append(f"code={self.code}")
        if self.subcode is not None:
            parts.append(f"subcode={self.subcode}")
        if self.fbtrace_id:
            parts.append(f"fbtrace_id={self.fbtrace_id}")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {
            "message": self.message,
            "category": self.category.value,
            "code": self.code,
            "subcode": self.subcode,
            "http_status": self.http_status,
            "retryable": self.retryable,
        }


# ---- Meta 错误码分类表 ----
# 限流：应用级 / 用户级 / 主页级 / 自定义级
RATE_LIMIT_CODES = {4, 17, 32, 613, 80002, 80003, 80004, 80005}
# 认证失效：Token 过期 / Session 无效
AUTH_CODES = {190, 102, 104, 460, 463, 467}
# 权限不足
PERMISSION_CODES = {10, 200, 210, 284, 294, 299}
# 临时性错误：服务不可用 / 未知错误
TEMPORARY_CODES = {1, 2}


def classify(
    code: Optional[int] = None,
    subcode: Optional[int] = None,
    http_status: Optional[int] = None,
    message: str = "",
) -> ErrorCategory:
    """按 Meta 错误码判定错误分类"""
    if code in RATE_LIMIT_CODES:
        return ErrorCategory.RATE_LIMIT
    if code in AUTH_CODES:
        return ErrorCategory.AUTH
    if code in PERMISSION_CODES:
        return ErrorCategory.PERMISSION
    if code == 100:
        # 100 语义依赖 subcode：
        #   subcode 33 → 对象不存在 / 权限不足（act_xxx does not exist）
        #   其余       → 参数错误，重试无意义
        if subcode in (33,):
            return ErrorCategory.PERMISSION
        return ErrorCategory.VALIDATION
    if code in TEMPORARY_CODES:
        return ErrorCategory.TEMPORARY
    if http_status and 500 <= http_status < 600:
        return ErrorCategory.TEMPORARY
    if code and 2000 <= code < 3000:  # 参数校验类
        return ErrorCategory.VALIDATION
    return ErrorCategory.UNKNOWN


def classify_facebook_error(exc: Exception) -> MetaApiError:
    """把 facebook_business 的 FacebookRequestError 转换为 MetaApiError"""
    if FacebookRequestError and isinstance(exc, FacebookRequestError):
        try:
            code = exc.api_error_code()
        except Exception:
            code = None
        try:
            subcode = exc.api_error_subcode()
        except Exception:
            subcode = None
        try:
            message = exc.api_error_message() or str(exc)
        except Exception:
            message = str(exc)
        try:
            http_status = exc.http_status()
        except Exception:
            http_status = None
        try:
            fbtrace_id = exc.body().get("error", {}).get("fbtrace_id")
        except Exception:
            fbtrace_id = None

        return MetaApiError(
            message,
            category=classify(code, subcode, http_status, message),
            code=code,
            subcode=subcode,
            http_status=http_status,
            fbtrace_id=fbtrace_id,
        )

    # 非 SDK 异常（网络超时等）默认按临时错误处理
    return MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
