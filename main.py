from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional
from pydantic import BaseModel

from config.settings import settings
from core.database import get_db, init_db, close_db
from core.logger import logger
from services.ads_manager import AdsManager
from services.risk_detector import RiskDetector
from services.analytics import AnalyticsEngine
from tasks.scheduler import scheduler
from tasks.celery_tasks import (
    fetch_account_insights,
    check_account_risk,
    generate_daily_report,
    generate_weekly_report,
)

# 初始化FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# ==================== 数据模型 ====================

class AccountInfo(BaseModel):
    """账户信息"""
    account_id: str
    account_name: str
    currency: str
    timezone: str
    daily_spend_limit: float

class CampaignInfo(BaseModel):
    """系列信息"""
    campaign_id: str
    name: str
    status: str
    objective: str
    daily_budget: Optional[float]

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
    """应用启动事件"""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    init_db()
    scheduler.start()
    logger.info("Application started successfully")

@app.on_event("shutdown")
async def shutdown():
    """应用关闭事件"""
    logger.info("Shutting down application")
    scheduler.stop()
    close_db()
    logger.info("Application shutdown complete")

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
    """获取今日花费"""
    try:
        ads_manager = AdsManager(db)
        spend = ads_manager.get_account_spend_today(account_id)
        
        return {
            "account_id": account_id,
            "spend": spend,
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

# ==================== 错误处理 ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """HTTP异常处理"""
    logger.error(f"HTTP Exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """通用异常处理"""
    logger.error(f"Unhandled Exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
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
