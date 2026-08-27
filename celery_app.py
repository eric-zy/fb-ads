"""Celery应用配置"""
from celery import Celery
from config.settings import settings
import os

# 创建Celery应用实例
celery_app = Celery('fb_ads_automation')

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
    result_expires=3600,  # 结果保留1小时
    worker_prefetch_multiplier=1,  # 防止任务堆积
    worker_max_tasks_per_child=1000,  # 工作进程重启间隔
)

# 自动发现任务
celery_app.autodiscover_tasks(['tasks'])

@celery_app.task(bind=True)
def debug_task(self):
    """调试任务"""
    print(f'Request: {self.request!r}')
