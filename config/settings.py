import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """应用配置管理"""

    # ========== 服务角色与跨服务配置 ==========
    # saas：国内业务服务；fb_connector：海外 Meta 接入服务。
    APP_ROLE: str = os.getenv("APP_ROLE", "saas")
    FB_ACCESS_MODE: str = os.getenv("FB_ACCESS_MODE", "direct")
    # connector 模式默认启用 Connector，避免只配置 FB_ACCESS_MODE 后，
    # 投放任务运行到 FBConnectorClient 才失败为“FB Connector 未启用”。
    FB_CONNECTOR_ENABLED: bool = os.getenv(
        "FB_CONNECTOR_ENABLED",
        "true" if FB_ACCESS_MODE == "connector" else "false",
    ).lower() == "true"
    FB_CONNECTOR_BASE_URL: str = os.getenv("FB_CONNECTOR_BASE_URL", "")
    FB_CONNECTOR_TIMEOUT: int = int(os.getenv("FB_CONNECTOR_TIMEOUT", "30"))
    # Insights 可能因 Meta 限流等待，并且海外端会同时处理多个账户；
    # 不与普通 Connector 请求共用 30 秒短超时。
    FB_CONNECTOR_REPORT_TIMEOUT: int = int(os.getenv("FB_CONNECTOR_REPORT_TIMEOUT", "300"))
    FB_CONNECTOR_SIGNING_KEY: str = os.getenv("FB_CONNECTOR_SIGNING_KEY", "")
    CONNECTOR_SERVICE_TOKEN: str = os.getenv("CONNECTOR_SERVICE_TOKEN", "")
    SAAS_CALLBACK_BASE_URL: str = os.getenv("SAAS_CALLBACK_BASE_URL", "")
    SAAS_INTERNAL_SIGNING_KEY: str = os.getenv("SAAS_INTERNAL_SIGNING_KEY", "")
    
    # ========== 基础配置 ==========
    APP_NAME: str = "Facebook Ads Automation"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    
    # ========== Facebook API 配置 ==========
    FB_APP_ID: str = os.getenv("FB_APP_ID", "")
    FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "")
    FB_LOGIN_CONFIG_ID: str = os.getenv("FB_LOGIN_CONFIG_ID", "")
    FB_ACCESS_TOKEN: str = os.getenv("FB_ACCESS_TOKEN", "")
    FB_ACCOUNT_ID: str = os.getenv("FB_ACCOUNT_ID", "")
    # Meta API 版本由部署环境显式覆盖；默认跟随当前 SDK 主版本。
    FB_API_VERSION: str = os.getenv("FB_API_VERSION", "v25.0")
    FB_OAUTH_REDIRECT_URI: str = os.getenv(
        "FB_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/v1/meta-auth/callback",
    )
    FB_OAUTH_SCOPES: str = os.getenv(
        "FB_OAUTH_SCOPES",
        "business_management,ads_management,ads_read,pages_show_list,pages_read_engagement",
    )
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
    FB_API_TIMEOUT: int = 30
    # 视频上传会持续写入请求体，不能复用普通 Graph API 的短超时。
    # 可通过环境变量覆盖，格式为秒；默认 15 分钟，适合 200MB 内素材。
    FB_VIDEO_CONNECT_TIMEOUT: int = int(os.getenv("FB_VIDEO_CONNECT_TIMEOUT", "30"))
    FB_VIDEO_UPLOAD_TIMEOUT: int = int(os.getenv("FB_VIDEO_UPLOAD_TIMEOUT", "900"))
    # Meta advideos resumable upload：实际 offset 由 Meta 返回，以下仅限制单片读取大小。
    FB_VIDEO_CHUNK_MAX_BYTES: int = int(os.getenv("FB_VIDEO_CHUNK_MAX_BYTES", str(10 * 1024 * 1024)))
    FB_VIDEO_PROCESSING_TIMEOUT: int = int(os.getenv("FB_VIDEO_PROCESSING_TIMEOUT", "900"))
    FB_VIDEO_STATUS_POLL_INTERVAL: int = int(os.getenv("FB_VIDEO_STATUS_POLL_INTERVAL", "15"))
    # 无海外 OSS 时，Connector 只在本地临时目录落盘一个素材；
    # 生产环境通过独立 media worker + tmpfs 限制并发和磁盘占用。
    CONNECTOR_MEDIA_TEMP_DIR: str = os.getenv("CONNECTOR_MEDIA_TEMP_DIR", "/tmp/fb-connector-media")
    CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES: int = int(
        os.getenv("CONNECTOR_MEDIA_MAX_DOWNLOAD_BYTES", str(1024 * 1024 * 1024))
    )
    # 即使未来横向扩展多个 media worker，同一广告账户仍只允许一个素材上传流程。
    CONNECTOR_MEDIA_ACCOUNT_LOCK_TTL: int = int(
        os.getenv("CONNECTOR_MEDIA_ACCOUNT_LOCK_TTL", "3600")
    )
    # 超过该时间仍处于 UPLOADING 的 Connector 媒体任务视为孤儿任务，
    # 允许下一次幂等请求或定时恢复任务重新入队。
    CONNECTOR_MEDIA_STALE_SECONDS: int = int(os.getenv("CONNECTOR_MEDIA_STALE_SECONDS", "1800"))
    # 海外视频上传允许 15 分钟；国内轮询必须覆盖该窗口并留出网络抖动余量。
    CONNECTOR_MEDIA_POLL_MAX_RETRIES: int = int(os.getenv("CONNECTOR_MEDIA_POLL_MAX_RETRIES", "80"))
    # 国内 Worker 的硬限制为 30 分钟，恢复阈值略留缓冲，避免重复派发仍在执行的任务。
    ASYNC_TASK_STALE_SECONDS: int = int(os.getenv("ASYNC_TASK_STALE_SECONDS", "2100"))
    # 海外完整投放创建可能包含多个 Meta 请求；国内轮询窗口必须覆盖恢复阈值，
    # 避免国内先判失败而海外任务仍在执行。
    FB_CONNECTOR_DELIVERY_POLL_MAX_RETRIES: int = int(
        os.getenv("FB_CONNECTOR_DELIVERY_POLL_MAX_RETRIES", "140")
    )
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

    # CORS：前端独立部署（3000/5173）时必须放行，否则 /api/* 会被浏览器拦截
    CORS_ORIGINS: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    )

    # ========== 素材上传配置 ==========
    MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", str(200 * 1024 * 1024)))  # 200MB
    MEDIA_STORAGE_PROVIDER: str = os.getenv("MEDIA_STORAGE_PROVIDER", "oss").lower()
    OSS_REGION: str = os.getenv("ADS_OSS_REGION", os.getenv("OSS_REGION", ""))
    OSS_ENDPOINT: str = os.getenv("ADS_OSS_ENDPOINT", os.getenv("OSS_ENDPOINT", "")) or (
        f"https://oss-{OSS_REGION}.aliyuncs.com" if OSS_REGION else ""
    )
    OSS_BUCKET: str = os.getenv("ADS_OSS_BUCKET", os.getenv("OSS_BUCKET", ""))
    OSS_BASE_PATH: str = os.getenv("OSS_BASE_PATH", "ossuser/oversea").strip("/")
    OSS_PLATFORM: str = os.getenv("OSS_PLATFORM", "meta").strip("/") or "meta"
    OSS_UPLOAD_EXPIRE_SECONDS: int = int(os.getenv("OSS_UPLOAD_EXPIRE_SECONDS", "900"))
    OSS_DOWNLOAD_EXPIRE_SECONDS: int = int(os.getenv("OSS_DOWNLOAD_EXPIRE_SECONDS", "900"))
    OSS_ACCESS_KEY_ID: str = os.getenv(
        "ADS_OSS_ACCESS_KEY_ID",
        os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", os.getenv("OSS_ACCESS_KEY_ID", "")),
    )
    OSS_ACCESS_KEY_SECRET: str = os.getenv(
        "ADS_OSS_ACCESS_KEY_SECRET",
        os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", os.getenv("OSS_ACCESS_KEY_SECRET", "")),
    )
    # Role ARN 是可选的，没有时直接使用 RAM 用户 AccessKey。
    OSS_STS_ROLE_ARN: str = os.getenv("OSS_STS_ROLE_ARN", "")
    OSS_STS_DURATION_SECONDS: int = int(os.getenv("OSS_STS_DURATION_SECONDS", "3600"))
    
    # ========== 通知配置 ==========
    NOTIFY_EMAIL: Optional[str] = os.getenv("NOTIFY_EMAIL")
    NOTIFY_DING_WEBHOOK: Optional[str] = os.getenv("NOTIFY_DING_WEBHOOK")
    NOTIFY_SLACK_WEBHOOK: Optional[str] = os.getenv("NOTIFY_SLACK_WEBHOOK")
    
    # ========== 多租户（SaaS）配置 ==========
    # 严格模式：开启后，执行租户级查询却没有租户上下文时直接抛错，
    # 而不是"不过滤返回全量"。生产环境强烈建议开启，开发环境可关闭以便调试。
    TENANT_STRICT_MODE: bool = os.getenv("TENANT_STRICT_MODE", "false").lower() == "true"
    # 默认租户：历史数据回填归属的租户 slug（迁移 0006 会创建/复用）
    DEFAULT_TENANT_SLUG: str = os.getenv("DEFAULT_TENANT_SLUG", "default")
    DEFAULT_TENANT_NAME: str = os.getenv("DEFAULT_TENANT_NAME", "默认租户")

    # ========== 任务调度配置 ==========
    SCHEDULE_FETCH_INSIGHTS_CRON: str = "0 */2 * * *"  # 每2小时
    SCHEDULE_RISK_CHECK_CRON: str = "0 * * * *"        # 每小时
    SCHEDULE_REPORT_DAILY_CRON: str = "0 8 * * *"      # 每天8点
    SCHEDULE_REPORT_WEEKLY_CRON: str = "0 9 * * 1"     # 每周一9点
    # 凭据到期巡检：Meta 长期 Token 固定 60 天且无 refresh 机制，必须定时巡检
    SCHEDULE_CREDENTIAL_CHECK_CRON: str = "0 9 * * *"   # 每天9点
    CREDENTIAL_EXPIRY_WARN_DAYS: int = int(os.getenv("CREDENTIAL_EXPIRY_WARN_DAYS", "7"))
    
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

    def validate_runtime_config(self) -> None:
        """校验当前部署角色所需配置，避免 Secret 放错服务器。"""
        role = self.APP_ROLE.strip().lower()
        if role not in {"saas", "fb_connector"}:
            raise ValueError("APP_ROLE 必须是 saas 或 fb_connector")
        if self.ENVIRONMENT.lower() == "production" and self.SECRET_KEY in {"", "your-secret-key", "change-me"}:
            raise ValueError("生产环境必须设置非默认 SECRET_KEY")
        if role == "fb_connector":
            required = {
                "FB_APP_ID": self.FB_APP_ID,
                "FB_APP_SECRET": self.FB_APP_SECRET,
                "FB_OAUTH_REDIRECT_URI": self.FB_OAUTH_REDIRECT_URI,
            }
            missing = [key for key, value in required.items() if not value]
            if missing:
                raise ValueError(f"FB Connector 缺少配置: {', '.join(missing)}")
        if role == "saas" and self.FB_ACCESS_MODE == "connector":
            required = {
                "FB_CONNECTOR_ENABLED": self.FB_CONNECTOR_ENABLED,
                "FB_CONNECTOR_BASE_URL": self.FB_CONNECTOR_BASE_URL,
                "FB_CONNECTOR_REPORT_TIMEOUT": self.FB_CONNECTOR_REPORT_TIMEOUT,
                "FB_CONNECTOR_SIGNING_KEY": self.FB_CONNECTOR_SIGNING_KEY,
                "CONNECTOR_SERVICE_TOKEN": self.CONNECTOR_SERVICE_TOKEN,
                "SAAS_CALLBACK_BASE_URL": self.SAAS_CALLBACK_BASE_URL,
            }
            missing = [key for key, value in required.items() if not value]
            if missing:
                raise ValueError(f"Connector 模式缺少配置: {', '.join(missing)}")
        if self.MEDIA_STORAGE_PROVIDER != "oss":
            raise ValueError("当前版本仅支持 MEDIA_STORAGE_PROVIDER=oss")
        required = {
            "OSS_REGION": self.OSS_REGION,
            "OSS_ENDPOINT": self.OSS_ENDPOINT,
            "OSS_BUCKET": self.OSS_BUCKET,
            "OSS_ACCESS_KEY_ID": self.OSS_ACCESS_KEY_ID,
            "OSS_ACCESS_KEY_SECRET": self.OSS_ACCESS_KEY_SECRET,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"OSS 存储缺少配置: {', '.join(missing)}")
        if not (900 <= self.OSS_UPLOAD_EXPIRE_SECONDS <= 43200):
            raise ValueError("OSS_UPLOAD_EXPIRE_SECONDS 必须在 900 到 43200 秒之间")
        if not (900 <= self.OSS_DOWNLOAD_EXPIRE_SECONDS <= 43200):
            raise ValueError("OSS_DOWNLOAD_EXPIRE_SECONDS 必须在 900 到 43200 秒之间")
        if not (900 <= self.OSS_STS_DURATION_SECONDS <= 43200):
            raise ValueError("OSS_STS_DURATION_SECONDS 必须在 900 到 43200 秒之间")

settings = Settings()
