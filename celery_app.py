"""Celery应用配置"""
from celery import Celery
from celery.schedules import crontab
from config.settings import settings
import os
import sys

# 将项目根目录加入 sys.path，确保 tasks 等模块可被导入
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 创建Celery应用实例
celery_app = Celery('fb_ads_automation')

# 设为当前进程默认 app，确保 @shared_task 在运行时解析到本项目实例
# （否则 shared_task 会绑定到无 broker 的 celery 默认 app，导致
#   delay() 走 pyamqp 连 RabbitMQ 5672 → ConnectionRefusedError）
celery_app.set_default()

# 从配置中加载设置
celery_app.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    timezone=settings.CELERY_TIMEZONE,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30分钟硬限制
    task_soft_time_limit=25 * 60,  # 25分钟软限制
    result_expires=3600,  # 结果保存1小时
    worker_prefetch_multiplier=1,  # 防止任务堆积
    worker_max_tasks_per_child=1000,  # 工作进程重启间隔
    broker_connection_retry_on_startup=True,  # Celery 6.0 起避免启动期 broker 重试警告
)

# ---------------------------------------------------------------------------
# Celery Beat 定时调度（设计文档第 5 / 24 节）
#
# 原先定时任务由 APScheduler 承担（tasks/scheduler.py，随 API 进程启动）。
# 问题：API 多副本部署时每个副本都会跑一遍调度，导致任务重复执行。
# 现统一交给 Celery Beat（独立进程，单点调度）。
#
# 启动： celery -A celery_app beat --loglevel=info
# ---------------------------------------------------------------------------
def _cron(expr: str) -> crontab:
    """把 5 段 cron 表达式（分 时 日 月 周）转换为 Celery crontab 计划"""
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式（应为 5 段）: {expr}")
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


celery_app.conf.beat_schedule = {
    "fetch-insights": {
        "task": "tasks.celery_tasks.fetch_all_accounts_insights",
        "schedule": _cron(settings.SCHEDULE_FETCH_INSIGHTS_CRON),
    },
    "risk-check": {
        "task": "tasks.celery_tasks.check_all_accounts_risk",
        "schedule": _cron(settings.SCHEDULE_RISK_CHECK_CRON),
    },
    "daily-reports": {
        "task": "tasks.celery_tasks.dispatch_daily_reports",
        "schedule": _cron(settings.SCHEDULE_REPORT_DAILY_CRON),
    },
    "weekly-reports": {
        "task": "tasks.celery_tasks.dispatch_weekly_reports",
        "schedule": _cron(settings.SCHEDULE_REPORT_WEEKLY_CRON),
    },
}

# 自动发现任务
celery_app.autodiscover_tasks(['tasks'])

# 显式导入任务模块，确保 shared_task 在 worker 启动时注册
#
# 注意：autodiscover_tasks(['tasks']) 只会导入 tasks 包本身（tasks/__init__.py），
# 不会递归导入 tasks.celery_tasks / tasks.campaign_tasks 等子模块。
# 若此处不显式导入，worker 收到任务时会报
#   Received unregistered task of type 'campaign.execute_job'
# （典型表现：Job 一直卡在 QUEUED，批量投放完全不执行）。
import logging as _logging

for _task_module in (
    "tasks.celery_tasks",
    "tasks.campaign_tasks",
    "tasks.meta_sync_tasks",  # Meta 账号管理 V1：BM / 广告账户同步
):
    try:
        __import__(_task_module)
    except ImportError as exc:  # pragma: no cover
        _logging.getLogger(__name__).warning(
            f"无法导入任务模块 {_task_module}: {exc}"
        )

@celery_app.task(bind=True)
def debug_task(self):
    """调试任务"""
    print(f'Request: {self.request!r}')
