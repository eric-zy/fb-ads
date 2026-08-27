import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """应用配置管理"""
    
    # ========== 基础配置 ==========
    APP_NAME: str = "Facebook Ads Automation"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    
    # ========== Facebook API 配置 ==========
    FB_APP_ID: str = os.getenv("FB_APP_ID", "")
    FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "")
    FB_ACCESS_TOKEN: str = os.getenv("FB_ACCESS_TOKEN", "")
    FB_ACCOUNT_ID: str = os.getenv("FB_ACCOUNT_ID", "")
    FB_API_TIMEOUT: int = 30
    FB_API_RETRY_COUNT: int = 3
    
    # ========== 数据库配置 ==========
    DB_TYPE: str = os.getenv("DB_TYPE", "postgresql")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.getenv("DB_NAME", "fb_ads_db")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    
    # MongoDB 配置
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str = "fb_ads_automation"
    
    # ========== Redis 配置 ==========
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD")
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))
    REDIS_TIMEOUT: int = 5
    
    # ========== Celery 配置 ==========
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list = ["json"]
    CELERY_TIMEZONE: str = "UTC"
    
    # ========== 风控配置 ==========
    RISK_ENABLE: bool = os.getenv("RISK_ENABLE", "true").lower() == "true"
    RISK_DAILY_SPEND_LIMIT: float = float(os.getenv("RISK_DAILY_SPEND_LIMIT", "10000"))
    RISK_DAILY_CTR_THRESHOLD: float = float(os.getenv("RISK_DAILY_CTR_THRESHOLD", "0.02"))
    RISK_DAILY_CPC_THRESHOLD: float = float(os.getenv("RISK_DAILY_CPC_THRESHOLD", "5.0"))
    RISK_FRAUD_SCORE_THRESHOLD: float = float(os.getenv("RISK_FRAUD_SCORE_THRESHOLD", "0.7"))
    RISK_ACCOUNT_FREEZE_DAYS: int = int(os.getenv("RISK_ACCOUNT_FREEZE_DAYS", "3"))
    RISK_CHECK_INTERVAL: int = 3600  # 检查间隔（秒）
    
    # ========== 日志配置 ==========
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/app.log")
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 10
    SENTRY_DSN: Optional[str] = os.getenv("SENTRY_DSN")
    
    # ========== API 配置 ==========
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    API_WORKERS: int = 4
    
    # ========== 通知配置 ==========
    NOTIFY_EMAIL: Optional[str] = os.getenv("NOTIFY_EMAIL")
    NOTIFY_DING_WEBHOOK: Optional[str] = os.getenv("NOTIFY_DING_WEBHOOK")
    NOTIFY_SLACK_WEBHOOK: Optional[str] = os.getenv("NOTIFY_SLACK_WEBHOOK")
    
    # ========== 任务调度配置 ==========
    SCHEDULE_FETCH_INSIGHTS_CRON: str = "0 */2 * * *"  # 每2小时
    SCHEDULE_RISK_CHECK_CRON: str = "0 * * * *"        # 每小时
    SCHEDULE_REPORT_DAILY_CRON: str = "0 8 * * *"      # 每天8点
    SCHEDULE_REPORT_WEEKLY_CRON: str = "0 9 * * 1"     # 每周一9点
    
    @property
    def database_url(self) -> str:
        """生成数据库连接URL"""
        if self.DB_TYPE == "postgresql":
            return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return ""
    
    @property
    def redis_url(self) -> str:
        """生成Redis连接URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()