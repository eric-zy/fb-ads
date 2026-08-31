# 添加到 main.py 的新API端点

from services.rate_limit import RateLimitManager
from services.publish_frequency_validator import PublishFrequencyValidator

# ==================== 速率限制和发布频次API ====================

@app.get("/api/v1/accounts/{account_id}/rate-limit-status")
async def get_rate_limit_status(account_id: str):
    """
    获取账户的API速率限制状态
    
    返回:
    - minute: 每分钟限制 (通常10次)
    - hour: 每小时限制 (通常200次)
    - day: 每天限制 (通常10000次)
    """
    try:
        rate_limiter = RateLimitManager(account_id)
        status = rate_limiter.get_status()
        
        return {
            "account_id": account_id,
            "status": "ok",
            "rate_limits": status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get rate limit status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/publish-frequency-check")
async def check_publish_frequency(account_id: str, hours: int = 24, 
                                 db: Session = Depends(get_db)):
    """
    检查账户的发布频次
    
    参数:
    - hours: 检查时间窗口 (小时)
    
    返回:
    - frequency_status: 'safe', 'warning', 'high_risk', 'critical'
    - campaigns_created: 时间窗口内创建的系列数
    - recommended_limit: 推荐的发布限制
    """
    try:
        validator = PublishFrequencyValidator(db)
        report = validator.check_campaign_publish_frequency(account_id, hours)
        
        return {
            "account_id": account_id,
            "timestamp": datetime.utcnow().isoformat(),
            "frequency_report": report
        }
    except Exception as e:
        logger.error(f"Failed to check publish frequency: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/account-health-check")
async def check_account_health(account_id: str, db: Session = Depends(get_db)):
    """
    检查账户整体健康状况
    
    返回:
    - is_healthy: 账户是否健康
    - status: 账户状态 (active, frozen, paused, suspended)
    - reason: 如果不健康，返回原因
    """
    try:
        validator = PublishFrequencyValidator(db)
        is_healthy, report = validator.validate_account_health(account_id)
        
        return {
            "account_id": account_id,
            "is_healthy": is_healthy,
            "health_report": report,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to check account health: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/safety-recommendations")
async def get_safety_recommendations(account_id: str, db: Session = Depends(get_db)):
    """
    获取账户的安全推荐措施
    
    返回:
    - overall_status: 整体状态 (healthy/unhealthy)
    - actions: 推荐的行动列表
      - priority: 'critical', 'high', 'medium', 'low'
      - type: 行动类型
      - message: 人类可读的消息
    """
    try:
        validator = PublishFrequencyValidator(db)
        recommendations = validator.recommend_action(account_id)
        
        return {
            "account_id": account_id,
            "recommendations": recommendations,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/safe-publish-interval")
async def get_safe_publish_interval(account_id: str, db: Session = Depends(get_db)):
    """
    获取安全的发布间隔时间
    
    返回:
    - recommended_interval_seconds: 建议的发布间隔 (秒)
    - message: 详细说明
    
    示例: 如果返回60秒，表示每次发布之间应该至少间隔60秒
    """
    try:
        validator = PublishFrequencyValidator(db)
        interval_info = validator.get_safe_publish_interval(account_id)
        
        return {
            "account_id": account_id,
            "interval_info": interval_info,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get safe publish interval: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/accounts/{account_id}/rate-limit-reset")
async def reset_rate_limit(account_id: str, window: str = None):
    """
    重置账户的速率限制计数器
    
    参数:
    - window: 要重置的窗口 ('minute', 'hour', 'day'), None表示全部重置
    
    注意: 这是一个管理员端点，应该谨慎使用
    """
    try:
        rate_limiter = RateLimitManager(account_id)
        success = rate_limiter.reset(window)
        
        return {
            "account_id": account_id,
            "window": window or "all",
            "success": success,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to reset rate limit: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/accounts/{account_id}/api-call-history")
async def get_api_call_history(account_id: str):
    """
    获取账户的API调用历史统计
    
    返回:
    - minute: 当前分钟内的调用次数
    - hour: 当前小时内的调用次数
    - day: 当前天内的调用次数
    """
    try:
        rate_limiter = RateLimitManager(account_id)
        status = rate_limiter.get_status()
        
        history = {
            "account_id": account_id,
            "api_calls": {
                "minute": status.get('minute', {}),
                "hour": status.get('hour', {}),
                "day": status.get('day', {})
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return history
    except Exception as e:
        logger.error(f"Failed to get API call history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
