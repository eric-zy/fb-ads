"""API中间件 - 日志、认证、速率限制"""
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from time import time
from typing import Callable
import uuid

from core.logger import logger
from services.rate_limit import RateLimitManager

class LoggingMiddleware:
    """请求日志中间件"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
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
            logger.error(f"[{request_id}] Request failed: {str(e)}")
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

class RateLimitMiddleware:
    """速率限制中间件"""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
        # 只对API端点应用速率限制
        if not request.url.path.startswith("/api/v1/accounts/"):
            return await call_next(request)
        
        # 从路径中提取account_id
        path_parts = request.url.path.split("/")
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
