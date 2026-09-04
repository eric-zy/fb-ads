"""API中间件 - 日志、认证、速率限制

注意：三个中间件都必须继承 starlette 的 BaseHTTPMiddleware。
FastAPI 的 app.add_middleware 对非 BaseHTTPMiddleware 的类按「纯 ASGI 中间件」
处理，会以 (scope, receive, send) 三个参数调用 __call__；
而此前类内定义的是 (request, call_next) 签名，导致每个请求抛
"__call__() takes 3 positional arguments but 4 were given" → 全部 500。
"""
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from time import time
from typing import Callable
import uuid

from core.auth import AuthManager
from core.logger import logger
from services.rate_limit import RateLimitManager


class AuthEnforcementMiddleware(BaseHTTPMiddleware):
    """统一 API 鉴权中间件（设计文档第 41.2 节：权限隔离）

    背景：main.py 中存在大量直接挂在 app 上的内联路由（sync / spend-today /
    risk-check / freeze / performance / reports / campaigns / batch-publish 等），
    均未加任何鉴权依赖，任何拿到地址的人都能直接操作广告账户。

    逐个给 20+ 路由补 Depends 容易遗漏，因此用中间件统一兜底：
    除白名单外，所有 /api/ 请求必须携带有效 JWT。
    """

    PUBLIC_PATHS = {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        # Meta 浏览器回调不携带本系统 Bearer Token；身份与租户由短时签名 state 校验。
        "/api/v1/meta-auth/callback",
        "/health",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 非 API 路径、白名单、CORS 预检一律放行
        if (
            not path.startswith("/api/")
            or path in self.PUBLIC_PATHS
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "缺少认证令牌"}
            )

        token = auth_header.split(" ", 1)[1]
        try:
            AuthManager.verify_token(token)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "无效的令牌"})

        return await call_next(request)

class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 生成请求ID
        request_id = str(uuid.uuid4())

        # 记录请求信息
        start_time = time()
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Client: {request.client.host if request.client else 'unknown'}"
        )

        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"[{request_id}] Request failed: {str(e)}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

        # 记录响应信息
        process_time = time() - start_time
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} - "
            f"Status: {response.status_code} - Time: {process_time:.3f}s"
        )

        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)

        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件

    仅对会真实调用 Meta API 的账户操作限流（防止打爆 Facebook API 配额）；
    风控/统计类本地数据库查询不消耗 Meta API 配额，豁免限流，
    以免风控页并发查询（6 个接口 + 30 秒轮询）被误伤触发 429。
    """

    # 本地查询接口，不调 Meta API，豁免限流
    EXEMPT_SUFFIXES = (
        "/account-health-check",
        "/fraud-score",
        "/risk-events",
        "/safety-recommendations",
        "/publish-frequency-check",
        "/rate-limit-status",
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 只对账户操作路径应用速率限制
        if not path.startswith("/api/v1/accounts/"):
            return await call_next(request)

        # 风控/统计类本地查询不消耗 Meta API 配额，豁免限流
        if any(path.endswith(suffix) for suffix in self.EXEMPT_SUFFIXES):
            return await call_next(request)

        # 从路径中提取account_id
        path_parts = path.split("/")
        if len(path_parts) < 5:
            return await call_next(request)

        account_id = path_parts[4]

        # 检查速率限制
        rate_limiter = RateLimitManager(account_id)

        # 检查小时限制
        if not rate_limiter.check_limit('hour'):
            logger.warning(f"Rate limit exceeded for account {account_id}")
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded"}
            )

        # 增加计数器
        rate_limiter.increment('minute')
        rate_limiter.increment('hour')
        rate_limiter.increment('day')

        response = await call_next(request)

        # 添加速率限制信息到响应头
        status = rate_limiter.get_status()
        response.headers["X-RateLimit-Limit"] = str(status['hour']['limit'])
        response.headers["X-RateLimit-Remaining"] = str(status['hour']['remaining'])
        response.headers["X-RateLimit-Used"] = str(status['hour']['used'])

        return response
