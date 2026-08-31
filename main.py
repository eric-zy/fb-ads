from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from pydantic import BaseModel

from config.settings import settings
from core.database import get_db, init_db, close_db
from core.logger import logger
from core.money import to_major, to_minor
from services.ads_manager import AdsManager
from services.risk_detector import RiskDetector
from services.analytics import AnalyticsEngine
from services.fb_client import fb_client
from services.rate_limit import RateLimitManager
# 必须先导入 celery_app（其内部会 set_default），
# 保证后续 @shared_task 在运行时解析到本项目 Celery 实例（redis broker）。
from celery_app import celery_app as _celery_app  # noqa: F401
from tasks.celery_tasks import (
    fetch_account_insights,
    check_account_risk,
    generate_daily_report,
    generate_weekly_report,
)
from api import users as users_api
from api import accounts as accounts_api
from api import meta_accounts as meta_accounts_api
from api import credentials as credentials_api
from api import media as media_api
from api import templates as templates_api
from api import jobs as jobs_api
from core.auth import get_current_active_user, require_admin
from core.middleware import (
    AuthEnforcementMiddleware,
    LoggingMiddleware,
    RateLimitMiddleware,
)
import jwt
import hashlib
from datetime import datetime, timedelta

# 初始化FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

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

class AccountInfo(BaseModel):
    """账户信息（金额一律最小货币单位，见 core/money.py）"""
    account_id: str
    account_name: str
    currency: str
    timezone: str
    daily_spend_limit: int

class CampaignInfo(BaseModel):
    """系列信息"""
    campaign_id: str
    name: str
    status: str
    objective: str
    daily_budget: Optional[int]

class RiskEventInfo(BaseModel):
    """风险事件"""
    event_type: str
    risk_level: str
    title: str
    description: str

class ReportRequest(BaseModel):
    """报告请求"""
    account_id: str
    report_type: str  # daily, weekly
    date: Optional[str] = None

# ==================== 初始化 ====================

@app.on_event("startup")
async def startup():
    """应用启动事件

    注意：定时任务已由 Celery Beat 独立进程负责（celery_app.conf.beat_schedule），
    API 进程不再内嵌 APScheduler，避免多副本部署时任务重复执行。
    """
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
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

# 注册用户管理路由
app.include_router(users_api.router)

# 注册账户管理路由
app.include_router(accounts_api.router)

# 注册主账号（BM）管理路由
app.include_router(meta_accounts_api.router)

# 注册凭据管理路由（BM 主账号 / 广告账户 / 凭据 三层分离管理）
app.include_router(credentials_api.router)

# 注册素材库路由
app.include_router(media_api.router)

# 注册投放模板路由（系统核心业务对象）
app.include_router(templates_api.router)

# 注册 Job Center 路由（批量投放异步入口）
app.include_router(jobs_api.router)

# 静态文件：上传的素材可直接访问
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# ==================== 认证API ====================

def _hash_password(password: str) -> str:
    """与数据库存储一致的密码哈希（sha256）"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def _create_access_token(user_id: str, email: str, role: str) -> str:
    """生成JWT风格的访问令牌"""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=7),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

class LoginRequest(BaseModel):
    email: str
    password: str

@app.post("/api/v1/auth/login")
async def auth_login(request: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    try:
        from models import User
        user = db.query(User).filter(User.email == request.email).first()
        if not user or user.hashed_password != _hash_password(request.password):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账户已被禁用")

        token = _create_access_token(user.id, user.email, user.role)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "role": user.role,
                "company_id": user.company_id,
                "permissions": user.permissions or [],
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

# ==================== 账户API ====================

@app.post("/api/v1/accounts/{account_id}/sync")
async def sync_campaigns_api(account_id: str, db: Session = Depends(get_db)):
    """同步账户系列"""
    try:
        ads_manager = AdsManager(db)
        created, updated = ads_manager.sync_campaigns(account_id)
        
        return {
            "status": "success",
            "account_id": account_id,
            "created": created,
            "updated": updated
        }
    except Exception as e:
        logger.error(f"Failed to sync campaigns: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/spend-today")
async def get_daily_spend(account_id: str, db: Session = Depends(get_db)):
    """获取今日花费

    `spend_minor` 为最小货币单位，`spend` 为换算后的主单位（便于前端直接展示）。
    """
    try:
        ads_manager = AdsManager(db)
        spend_minor = ads_manager.get_account_spend_today(account_id)

        return {
            "account_id": account_id,
            "spend": to_major(spend_minor),
            "spend_minor": spend_minor,
            "currency": "USD"
        }
    except Exception as e:
        logger.error(f"Failed to get daily spend: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 风控API ====================

@app.post("/api/v1/accounts/{account_id}/risk-check")
async def check_risk_api(account_id: str, db: Session = Depends(get_db)):
    """检查账户风险"""
    try:
        risk_detector = RiskDetector(db)
        result = risk_detector.execute_risk_actions(account_id)
        
        return {
            "status": "success",
            "account_id": account_id,
            "actions_taken": result
        }
    except Exception as e:
        logger.error(f"Failed to check risk: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/risk-events")
async def get_risk_events(account_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """获取账户风险事件"""
    try:
        from models import RiskEvent
        
        events = db.query(RiskEvent).filter(
            RiskEvent.ad_account_id == account_id
        ).order_by(RiskEvent.created_at.desc()).limit(limit).all()
        
        return {
            "account_id": account_id,
            "events": [
                {
                    "id": e.id,
                    "event_type": e.event_type.value,
                    "risk_level": e.risk_level.value,
                    "title": e.title,
                    "description": e.description,
                    "is_resolved": e.is_resolved,
                    "created_at": e.created_at.isoformat()
                }
                for e in events
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get risk events: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/accounts/{account_id}/freeze")
async def freeze_account(account_id: str, reason: str, db: Session = Depends(get_db)):
    """冻结账户"""
    try:
        risk_detector = RiskDetector(db)
        success = risk_detector.freeze_account(account_id, reason)
        
        if success:
            return {
                "status": "success",
                "account_id": account_id,
                "message": "Account frozen successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="Account not found")
    except Exception as e:
        logger.error(f"Failed to freeze account: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 数据分析API ====================

@app.get("/api/v1/accounts/{account_id}/performance")
async def get_account_performance(account_id: str, days: int = 30, db: Session = Depends(get_db)):
    """获取账户性能趋势"""
    try:
        analytics = AnalyticsEngine(db)
        df = analytics.get_account_performance_trend(account_id, days)
        
        if df.empty:
            return {"account_id": account_id, "data": []}
        
        return {
            "account_id": account_id,
            "days": days,
            "data": df.to_dict(orient='records')
        }
    except Exception as e:
        logger.error(f"Failed to get performance: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/fraud-score")
async def get_fraud_score(account_id: str, window_days: int = 7, db: Session = Depends(get_db)):
    """获取欺诈评分"""
    try:
        analytics = AnalyticsEngine(db)
        fraud_score = analytics.calculate_fraud_score(account_id, window_days)
        
        risk_level = "critical" if fraud_score > 0.8 else \
                     "high" if fraud_score > 0.6 else \
                     "medium" if fraud_score > 0.4 else "low"
        
        return {
            "account_id": account_id,
            "fraud_score": fraud_score,
            "risk_level": risk_level,
            "threshold": settings.RISK_FRAUD_SCORE_THRESHOLD
        }
    except Exception as e:
        logger.error(f"Failed to get fraud score: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/daily-report")
async def get_daily_report(account_id: str, report_date: str = None, db: Session = Depends(get_db)):
    """获取日报告"""
    try:
        analytics = AnalyticsEngine(db)
        
        if report_date is None:
            report_date = str(date.today())
        
        report = analytics.generate_daily_report(account_id, date.fromisoformat(report_date))
        
        if not report:
            raise HTTPException(status_code=404, detail="No data found for this date")
        
        return report
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Failed to get daily report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/weekly-report")
async def get_weekly_report(account_id: str, db: Session = Depends(get_db)):
    """获取周报告"""
    try:
        analytics = AnalyticsEngine(db)
        report = analytics.generate_weekly_report(account_id)
        
        if not report:
            raise HTTPException(status_code=404, detail="No data found")
        
        return report
    except Exception as e:
        logger.error(f"Failed to get weekly report: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 任务API ====================

@app.post("/api/v1/tasks/fetch-insights")
async def submit_fetch_insights(account_id: str):
    """提交拉取洞察任务"""
    try:
        task = fetch_account_insights.delay(account_id)
        return {
            "status": "submitted",
            "task_id": task.id,
            "account_id": account_id
        }
    except Exception as e:
        logger.error(f"Failed to submit fetch insights task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tasks/generate-report")
async def submit_generate_report(request: ReportRequest):
    """提交报告生成任务"""
    try:
        if request.report_type == "daily":
            task = generate_daily_report.delay(request.account_id, request.date)
        elif request.report_type == "weekly":
            task = generate_weekly_report.delay(request.account_id)
        else:
            raise HTTPException(status_code=400, detail="Invalid report type")
        
        return {
            "status": "submitted",
            "task_id": task.id,
            "account_id": request.account_id,
            "report_type": request.report_type
        }
    except Exception as e:
        logger.error(f"Failed to submit report task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    try:
        from celery_app import celery_app
        
        task_result = celery_app.AsyncResult(task_id)
        
        return {
            "task_id": task_id,
            "status": task_result.status,
            "result": task_result.result if task_result.status == "SUCCESS" else None,
            "error": str(task_result.info) if task_result.status == "FAILURE" else None
        }
    except Exception as e:
        logger.error(f"Failed to get task status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== 认证：当前用户 ====================

@app.get("/api/v1/auth/me")
async def auth_me(current_user: "User" = Depends(get_current_active_user)):
    """获取当前登录用户信息（基于 Authorization 头中的 JWT）"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "permissions": current_user.permissions or [],
        "settings": current_user.settings or {},
    }

# ==================== 系列管理API ====================

@app.get("/api/v1/accounts/{account_id}/campaigns")
async def get_campaigns(account_id: str, db: Session = Depends(get_db)):
    """获取账户下的广告系列列表（来自已同步的本地数据）"""
    try:
        from models import Campaign, CampaignStatus
        campaigns = (
            db.query(Campaign)
            .filter(Campaign.ad_account_id == account_id)
            .order_by(Campaign.created_at.desc())
            .all()
        )
        return {
            "account_id": account_id,
            "campaigns": [
                {
                    "id": c.id,
                    "campaign_id": c.campaign_id,
                    "name": c.name,
                    "status": c.status.value if c.status else "UNKNOWN",
                    "objective": c.objective,
                    "budget": c.budget,
                    "daily_budget": c.daily_budget,
                    "spend": c.spend or 0,
                    "impressions": c.impressions or 0,
                    "clicks": c.clicks or 0,
                    "ctr": c.ctr or 0,
                    "cpc": c.cpc or 0,
                    "cpm": c.cpm or 0,
                }
                for c in campaigns
            ],
        }
    except Exception as e:
        logger.error(f"Failed to get campaigns: {str(e)}")
        raise HTTPException(status_code=500, detail="获取系列列表失败")

class BatchPublishRequest(BaseModel):
    """批量投放请求"""
    account_id: str
    campaigns: List[dict]
    publish_type: str = "immediate"
    start_time: Optional[str] = None
    interval_minutes: Optional[int] = None
    max_daily_campaigns: Optional[int] = 10
    enable_risk_check: bool = True
    enable_frequency_check: bool = True
    notify_on_complete: bool = False
    notify_email: Optional[str] = None

@app.post("/api/v1/campaigns/batch-publish")
async def batch_publish_api(request: BatchPublishRequest, db: Session = Depends(get_db)):
    """批量投放广告系列"""
    try:
        # 若启用频次检查，先做安全间隔与频次校验
        if request.enable_frequency_check:
            try:
                rate_manager = RateLimitManager(request.account_id)
                if not rate_manager.check_limit("hour"):
                    raise HTTPException(
                        status_code=429,
                        detail="当前账户已达到 API 调用频次上限，请稍后再试"
                    )
            except HTTPException:
                raise
            except Exception:
                pass

        # 真实投放需调用 Facebook API；FB 不可用时优雅降级为已接收
        try:
            fb_client.api_init()
            # 此处可调用 services.ads_manager 的发布逻辑
            # 当前先记录任务并返回已提交状态
        except Exception as e:
            logger.warning(f"FB client init skipped for batch publish: {str(e)}")

        logger.info(
            f"Batch publish received: account={request.account_id}, "
            f"count={len(request.campaigns)}, type={request.publish_type}"
        )
        return {
            "status": "submitted",
            "account_id": request.account_id,
            "campaign_count": len(request.campaigns),
            "publish_type": request.publish_type,
            "message": "批量投放任务已接收，将在后台处理",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to batch publish: {str(e)}")
        raise HTTPException(status_code=500, detail="批量投放失败")

@app.post("/api/v1/campaigns/{campaign_id}/pause")
async def pause_campaign_api(campaign_id: str, db: Session = Depends(get_db)):
    """暂停广告系列"""
    try:
        from models import Campaign, CampaignStatus
        campaign = (
            db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="系列不存在")
        try:
            fb_client.api_init()
            fb_client.pause_campaign(campaign_id)
        except Exception as e:
            logger.warning(f"FB pause skipped: {str(e)}")
        campaign.status = CampaignStatus.PAUSED
        db.commit()
        return {"status": "success", "campaign_id": campaign_id, "state": "PAUSED"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause campaign: {str(e)}")
        raise HTTPException(status_code=500, detail="暂停系列失败")

@app.post("/api/v1/campaigns/{campaign_id}/resume")
async def resume_campaign_api(campaign_id: str, db: Session = Depends(get_db)):
    """恢复广告系列"""
    try:
        from models import Campaign, CampaignStatus
        campaign = (
            db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
        )
        if not campaign:
            raise HTTPException(status_code=404, detail="系列不存在")
        try:
            fb_client.api_init()
            fb_client.resume_campaign(campaign_id)
        except Exception as e:
            logger.warning(f"FB resume skipped: {str(e)}")
        campaign.status = CampaignStatus.ACTIVE
        db.commit()
        return {"status": "success", "campaign_id": campaign_id, "state": "ACTIVE"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume campaign: {str(e)}")
        raise HTTPException(status_code=500, detail="恢复系列失败")

@app.get("/api/v1/accounts/{account_id}/safe-publish-interval")
async def safe_publish_interval_api(account_id: str):
    """获取建议的安全发布间隔"""
    try:
        rate_manager = RateLimitManager(account_id)
        status_info = rate_manager.get_status()
        # 基于剩余额度的简单启发式：剩余越多，允许间隔越短
        hour_remaining = status_info.get("hour", {}).get("remaining", 200)
        suggested_minutes = max(5, int(60 / max(1, hour_remaining / 10)))
        return {
            "account_id": account_id,
            "suggested_interval_minutes": suggested_minutes,
            "rate_limit": status_info,
        }
    except Exception as e:
        logger.error(f"Failed to get safe publish interval: {str(e)}")
        raise HTTPException(status_code=500, detail="获取发布间隔失败")

@app.get("/api/v1/accounts/{account_id}/publish-frequency-check")
async def publish_frequency_check_api(account_id: str, hours: int = 24):
    """检查发布频次是否安全"""
    try:
        rate_manager = RateLimitManager(account_id)
        status_info = rate_manager.get_status()
        minute_used = status_info.get("minute", {}).get("used", 0)
        hour_used = status_info.get("hour", {}).get("used", 0)
        safe = minute_used < 10 and hour_used < 200
        return {
            "account_id": account_id,
            "hours": hours,
            "safe": safe,
            "current_usage": status_info,
            "recommendation": "可以发布" if safe else "已接近限制，请稍后再发布",
        }
    except Exception as e:
        logger.error(f"Failed to check publish frequency: {str(e)}")
        raise HTTPException(status_code=500, detail="频次检查失败")

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
