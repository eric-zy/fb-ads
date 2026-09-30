from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from config.settings import settings
from core.database import get_db, init_db, close_db
from core.logger import logger
# 必须先导入 celery_app（其内部会 set_default），
# 保证后续 @shared_task 在运行时解析到本项目 Celery 实例（redis broker）。
from celery_app import celery_app as _celery_app  # noqa: F401
from api import tenants as tenants_api
from api import users as users_api
from api import accounts as accounts_api
from api import meta_accounts as meta_accounts_api
from api import credentials as credentials_api
from api import meta_auth as meta_auth_api
from api import meta_pages as meta_pages_api
from api import meta_connections as meta_connections_api
from api import media as media_api
from api import creative_asset_groups as creative_asset_groups_api
from api import creative_asset_tags as creative_asset_tags_api
from api import templates as templates_api
from api import jobs as jobs_api
from api import campaigns as campaigns_api
from api import reports as reports_api
from api import workbench as workbench_api
from api import sinan_integration as sinan_api
from api import connector_callbacks as connector_callbacks_api
from api import connector_callbacks_insights as connector_callbacks_insights_api
from api import risk_control as risk_control_api
from api import meta_targeting as meta_targeting_api
from api import meta_audiences as meta_audiences_api
from api import meta_tracking_assets as meta_tracking_assets_api
from api.targeting_packages import region_router as region_groups_api_router, package_router as targeting_packages_api_router
from core.auth import AuthManager, get_current_active_user
from core.tenant import bypass_tenant
from core.middleware import (
    AuthEnforcementMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
)
from models import User
from datetime import timedelta

# 初始化FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

@app.get("/api/v1/public/locale")
async def public_locale(request: Request):
    """Return a coarse locale hint from reverse-proxy country headers."""
    country = (request.headers.get("CF-IPCountry") or request.headers.get("X-Country-Code") or "").upper()
    if country:
        return {"locale": "zh" if country in {"CN", "TW", "HK", "MO"} else "en"}
    # Keep browser-language detection as the client-side fallback when no
    # trusted reverse-proxy GeoIP header is available.
    return {"locale": None}

# ==================== 中间件 ====================
# 注意：Starlette 中后添加的中间件在外层、先执行。
# 请求进入顺序 = CORS → 日志 → 统一鉴权 → 限流 → 路由。
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthEnforcementMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型 ====================

# ==================== 初始化 ====================

@app.on_event("startup")
async def startup():
    """应用启动事件

    注意：定时任务已由 Celery Beat 独立进程负责（celery_app.conf.beat_schedule），
    API 进程不再内嵌 APScheduler，避免多副本部署时任务重复执行。
    """
    settings.validate_runtime_config()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} role={settings.APP_ROLE}")
    logger.info(
        f"[startup] CELERY_BROKER_URL={settings.CELERY_BROKER_URL!r} "
        f"REDIS_HOST={settings.REDIS_HOST!r} REDIS_PORT={settings.REDIS_PORT}"
    )
    try:
        from celery_app import celery_app as _ca

        logger.info(
            f"[startup] celery_app.broker_url={_ca.conf.broker_url!r} "
            f"transport={getattr(_ca.connection(), 'transport', None)!r}"
        )
    except Exception as _e:  # pragma: no cover
        logger.warning(f"[startup] 无法读取 celery_app broker 配置: {_e}")
    # 开发环境自动建表；生产环境请使用 alembic upgrade head 管理表结构
    init_db()
    logger.info("Application started successfully")

@app.on_event("shutdown")
async def shutdown():
    """应用关闭事件"""
    logger.info("Shutting down application")
    close_db()
    logger.info("Application shutdown complete")

# 注册租户管理路由（SaaS 多租户：租户开通/配额/启停）
app.include_router(tenants_api.router)

# 注册用户管理路由
app.include_router(users_api.router)

# 注册账户管理路由
app.include_router(accounts_api.router)

# 注册主账号（BM）管理路由
app.include_router(meta_accounts_api.router)

# 注册凭据管理路由（BM 主账号 / 广告账户 / 凭据 三层分离管理）
app.include_router(credentials_api.router)

# Meta OAuth 授权（管理员选择 BM 后授权，回调自动加密保存 Token）
app.include_router(meta_auth_api.router)
app.include_router(meta_pages_api.router)
app.include_router(meta_connections_api.router)
from api import operations as operations_api
app.include_router(operations_api.router)
from api import roles as roles_api
app.include_router(roles_api.router)
from api import account_groups as account_groups_api
app.include_router(account_groups_api.router)
from api import account_pool as account_pool_api
app.include_router(account_pool_api.router)
from api import account_dispatch as account_dispatch_api
app.include_router(account_dispatch_api.router)

# 注册素材库路由
app.include_router(media_api.router)
app.include_router(creative_asset_groups_api.router)
app.include_router(creative_asset_tags_api.router)

# 注册投放模板路由（系统核心业务对象）
app.include_router(templates_api.router)

# 注册 Job Center 路由（批量投放异步入口）
app.include_router(jobs_api.router)
app.include_router(campaigns_api.router)
app.include_router(reports_api.router)
app.include_router(workbench_api.router)
app.include_router(sinan_api.router)
app.include_router(connector_callbacks_api.router)
app.include_router(connector_callbacks_insights_api.router)
app.include_router(risk_control_api.router)
app.include_router(meta_targeting_api.router)
app.include_router(meta_audiences_api.router)
app.include_router(meta_tracking_assets_api.router)
app.include_router(region_groups_api_router)
app.include_router(targeting_packages_api_router)

# ==================== 认证API ====================

def _hash_password(password: str) -> str:
    """兼容旧调用方，统一使用 AuthManager 的强哈希实现。"""
    return AuthManager.hash_password(password)

def _create_access_token(user_id: str, email: str, role: str, tenant_id: str = None) -> str:
    """生成统一认证模块签发的短期访问令牌。"""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "tid": tenant_id,
    }
    return AuthManager.create_access_token(payload, expires_delta=timedelta(hours=24))

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/v1/auth/login")
async def auth_login(request: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    try:
        from models import User, Role
        # 登录请求尚未携带 JWT，无法建立租户上下文。认证阶段必须先
        # 跨租户定位账号，签发 token 后后续请求再恢复租户隔离。
        with bypass_tenant():
            user = db.query(User).filter(User.username == request.username.strip()).first()
            if not user or not AuthManager.verify_password(request.password, user.hashed_password):
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            if not user.is_active:
                raise HTTPException(status_code=403, detail="账户已被禁用")

            if AuthManager.needs_password_rehash(user.hashed_password):
                user.hashed_password = AuthManager.hash_password(request.password)
                db.commit()

            role_permissions = []
            if getattr(user, "role_id", None):
                role = db.query(Role).filter(Role.id == user.role_id).first()
                role_permissions = role.permissions if role else []
        effective_permissions = sorted(set((user.permissions or []) + (role_permissions or [])))
        token = _create_access_token(user.id, user.email, user.role, user.tenant_id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "tenant_id": user.tenant_id,
                "company_id": user.company_id,  # 已废弃，兼容老前端
                "is_platform_admin": user.is_platform_admin(),
                "permissions": effective_permissions,
                "settings": user.settings or {},
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        raise HTTPException(status_code=500, detail="登录失败")

@app.post("/api/v1/auth/logout")
async def auth_logout():
    """用户登出（前端清除 token 即可，后端无状态）"""
    return {"status": "success", "message": "登出成功"}

# ==================== 健康检查 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT
    }

# ==================== 认证：当前用户 ====================

@app.get("/api/v1/auth/me")
async def auth_me(current_user: "User" = Depends(get_current_active_user)):
    """获取当前登录用户信息（基于 Authorization 头中的 JWT）"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role,
        "tenant_id": getattr(current_user, "tenant_id", None),
        "company_id": current_user.company_id,  # 已废弃，兼容老前端
        "is_platform_admin": current_user.is_platform_admin(),
        "permissions": sorted(set(current_user.permissions or [])),
        "settings": current_user.settings or {},
    }

# ==================== 错误处理 ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理

    必须返回 `detail` 字段：全站前端统一按 `error.response.data.detail`
    读取后端原因（40+ 处）。此前只返回 `error`，导致所有错误提示都显示为
    "失败：undefined"。
    `error` 字段一并保留，兼容历史调用方。
    """
    logger.error(f"HTTP Exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error": exc.detail},
    )

@app.exception_handler(PermissionError)
async def tenant_permission_error_handler(request, exc):
    """租户越权处理（core.tenant 抛出）

    典型场景：缺少租户上下文时创建租户级数据、跨租户"数据搬家"、租户修改平台共享数据。
    转成 403 + detail，避免退化成 500 Internal server error。
    """
    logger.warning(f"Tenant permission denied: {exc}")
    return JSONResponse(
        status_code=403,
        content={"detail": str(exc), "error": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理"""
    logger.error(f"Unhandled Exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": "Internal server error"},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        reload=settings.DEBUG
    )
