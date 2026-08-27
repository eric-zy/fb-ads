"""APScheduler任务调度器"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import pytz

from config.settings import settings
from core.logger import logger
from tasks.celery_tasks import (
    fetch_all_accounts_insights,
    check_all_accounts_risk,
    generate_daily_report,
    generate_weekly_report,
)
from sqlalchemy.orm import Session
from core.database import SessionLocal

# 创建调度器实例
scheduler = BackgroundScheduler(timezone=pytz.UTC)

def schedule_fetch_insights():
    """定时拉取所有账户的洞察数据"""
    logger.info("Scheduled task: fetch_all_accounts_insights")
    fetch_all_accounts_insights.delay()

def schedule_risk_check():
    """定时检查所有账户的风险"""
    logger.info("Scheduled task: check_all_accounts_risk")
    from tasks.celery_tasks import check_all_accounts_risk
    check_all_accounts_risk.delay()

def schedule_daily_reports():
    """定时生成日报告"""
    logger.info("Scheduled task: generate_daily_report")
    db = SessionLocal()
    try:
        from models import AdAccount
        accounts = db.query(AdAccount).filter(AdAccount.is_active == True).all()
        for account in accounts:
            generate_daily_report.apply_async(
                args=(account.account_id,),
                countdown=5
            )
    finally:
        db.close()

def schedule_weekly_reports():
    """定时生成周报告"""
    logger.info("Scheduled task: generate_weekly_report")
    db = SessionLocal()
    try:
        from models import AdAccount
        accounts = db.query(AdAccount).filter(AdAccount.is_active == True).all()
        for account in accounts:
            generate_weekly_report.apply_async(
                args=(account.account_id,),
                countdown=5
            )
    finally:
        db.close()

def init_scheduler():
    """初始化所有定时任务"""
    try:
        logger.info("Initializing APScheduler...")
        
        # 解析Cron表达式
        def parse_cron(cron_expr: str):
            """解析Cron表达式为APScheduler参数"""
            parts = cron_expr.split()
            if len(parts) != 5:
                raise ValueError(f"Invalid cron expression: {cron_expr}")
            
            minute, hour, day, month, day_of_week = parts
            return {
                'minute': minute if minute != '*' else None,
                'hour': hour if hour != '*' else None,
                'day': day if day != '*' else None,
                'month': month if month != '*' else None,
                'day_of_week': day_of_week if day_of_week != '*' else None,
            }
        
        # 添加拉取洞察任务
        fetch_cron = parse_cron(settings.SCHEDULE_FETCH_INSIGHTS_CRON)
        scheduler.add_job(
            schedule_fetch_insights,
            trigger=CronTrigger(**{k: v for k, v in fetch_cron.items() if v is not None}),
            id='fetch_insights_job',
            name='Fetch Insights',
            replace_existing=True
        )
        logger.info(f"Added job: fetch_insights ({settings.SCHEDULE_FETCH_INSIGHTS_CRON})")
        
        # 添加风险检查任务
        risk_cron = parse_cron(settings.SCHEDULE_RISK_CHECK_CRON)
        scheduler.add_job(
            schedule_risk_check,
            trigger=CronTrigger(**{k: v for k, v in risk_cron.items() if v is not None}),
            id='risk_check_job',
            name='Risk Check',
            replace_existing=True
        )
        logger.info(f"Added job: risk_check ({settings.SCHEDULE_RISK_CHECK_CRON})")
        
        # 添加日报告任务
        daily_cron = parse_cron(settings.SCHEDULE_REPORT_DAILY_CRON)
        scheduler.add_job(
            schedule_daily_reports,
            trigger=CronTrigger(**{k: v for k, v in daily_cron.items() if v is not None}),
            id='daily_report_job',
            name='Daily Report',
            replace_existing=True
        )
        logger.info(f"Added job: daily_report ({settings.SCHEDULE_REPORT_DAILY_CRON})")
        
        # 添加周报告任务
        weekly_cron = parse_cron(settings.SCHEDULE_REPORT_WEEKLY_CRON)
        scheduler.add_job(
            schedule_weekly_reports,
            trigger=CronTrigger(**{k: v for k, v in weekly_cron.items() if v is not None}),
            id='weekly_report_job',
            name='Weekly Report',
            replace_existing=True
        )
        logger.info(f"Added job: weekly_report ({settings.SCHEDULE_REPORT_WEEKLY_CRON})")
        
        logger.info("APScheduler initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {str(e)}")
        raise

def start():
    """启动调度器"""
    if not scheduler.running:
        init_scheduler()
        scheduler.start()
        logger.info("APScheduler started")

def stop():
    """停止调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler stopped")
