"""Celery异步任务定义"""
from celery import shared_task
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.logger import logger
from config.settings import settings
from services.ads_manager import AdsManager
from services.risk_detector import RiskDetector
from services.analytics import AnalyticsEngine
from services.notifications import NotificationService

# ==================== 洞察数据采集 ====================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_account_insights(self, account_id: str, days: int = 1) -> Dict:
    """拉取账户洞察数据
    
    Args:
        account_id: 广告账户ID
        days: 采集天数，默认1天
    
    Returns:
        采集结果统计
    """
    db = SessionLocal()
    try:
        logger.info(f"Fetching insights for account {account_id}")
        
        ads_manager = AdsManager(db)
        start_date = (date.today() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = date.today().strftime('%Y-%m-%d')
        
        insights_count = ads_manager.fetch_insights(account_id, start_date, end_date)
        
        logger.info(f"Successfully fetched {insights_count} insights for {account_id}")
        return {
            "status": "success",
            "account_id": account_id,
            "insights_count": insights_count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to fetch insights for {account_id}: {str(exc)}")
        # 重试
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fetch_all_accounts_insights(self, days: int = 1) -> Dict:
    """拉取所有账户的洞察数据"""
    db = SessionLocal()
    try:
        from models import AdAccount, SystemStatus
        
        # 只处理系统侧允许参与投放的账户（历史上这里用的 is_active 列并不存在，
        # 导致定时任务每次都抛错、实际一次都没跑起来）
        accounts = (
            db.query(AdAccount)
            .filter(AdAccount.system_status == SystemStatus.ACTIVE.value)
            .all()
        )
        results = []
        
        for account in accounts:
            try:
                result = fetch_account_insights.apply_async(
                    args=(account.account_id, days),
                    countdown=5  # 错开请求
                )
                results.append(result.id)
            except Exception as e:
                logger.error(f"Failed to submit task for {account.account_id}: {str(e)}")
        
        logger.info(f"Submitted {len(results)} insight fetch tasks")
        return {"status": "submitted", "task_count": len(results)}
    finally:
        db.close()

# ==================== 风险检测 ====================

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def check_account_risk(self, account_id: str) -> Dict:
    """检查账户风险
    
    Args:
        account_id: 广告账户ID
    
    Returns:
        风险检查结果
    """
    db = SessionLocal()
    try:
        if not settings.RISK_ENABLE:
            logger.info("Risk detection is disabled")
            return {"status": "disabled"}
        
        logger.info(f"Checking risk for account {account_id}")
        
        risk_detector = RiskDetector(db)
        
        # 执行风险检测
        results = risk_detector.execute_risk_actions(account_id)
        
        logger.info(f"Risk check completed for {account_id}: {results}")
        
        # 如果有风险，发送通知
        if results.get('events_created', 0) > 0:
            notify_risk_events.delay(account_id)
        
        return {
            "status": "success",
            "account_id": account_id,
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to check risk for {account_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@shared_task(bind=True, max_retries=2)
def check_all_accounts_risk(self) -> Dict:
    """检查所有账户的风险"""
    db = SessionLocal()
    try:
        from models import AdAccount, SystemStatus
        
        # 只处理系统侧允许参与投放的账户（历史上这里用的 is_active 列并不存在，
        # 导致定时任务每次都抛错、实际一次都没跑起来）
        accounts = (
            db.query(AdAccount)
            .filter(AdAccount.system_status == SystemStatus.ACTIVE.value)
            .all()
        )
        results = []
        
        for account in accounts:
            try:
                result = check_account_risk.apply_async(
                    args=(account.account_id,),
                    countdown=3
                )
                results.append(result.id)
            except Exception as e:
                logger.error(f"Failed to submit risk check for {account.account_id}: {str(e)}")
        
        logger.info(f"Submitted {len(results)} risk check tasks")
        return {"status": "submitted", "task_count": len(results)}
    finally:
        db.close()

# ==================== 报告生成 ====================

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_daily_report(self, account_id: str, report_date: Optional[str] = None) -> Dict:
    """生成日报告
    
    Args:
        account_id: 广告账户ID
        report_date: 报告日期 (YYYY-MM-DD格式), 默认为昨天
    
    Returns:
        报告生成结果
    """
    db = SessionLocal()
    try:
        logger.info(f"Generating daily report for {account_id}")
        
        if report_date is None:
            report_date = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        report_date_obj = datetime.strptime(report_date, '%Y-%m-%d').date()
        
        analytics = AnalyticsEngine(db)
        report = analytics.generate_daily_report(account_id, report_date_obj)
        
        # 发送报告通知
        if report:
            notify_daily_report.delay(account_id, report_date)
        
        logger.info(f"Daily report generated for {account_id}")
        return {
            "status": "success",
            "account_id": account_id,
            "report_date": report_date,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to generate daily report: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_weekly_report(self, account_id: str) -> Dict:
    """生成周报告
    
    Args:
        account_id: 广告账户ID
    
    Returns:
        报告生成结果
    """
    db = SessionLocal()
    try:
        logger.info(f"Generating weekly report for {account_id}")
        
        analytics = AnalyticsEngine(db)
        report = analytics.generate_weekly_report(account_id)
        
        # 发送报告通知
        if report:
            notify_weekly_report.delay(account_id)
        
        logger.info(f"Weekly report generated for {account_id}")
        return {
            "status": "success",
            "account_id": account_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to generate weekly report: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

# ==================== 通知服务 ====================

@shared_task(bind=True, max_retries=2)
def notify_risk_events(self, account_id: str) -> Dict:
    """发送风险事件通知"""
    db = SessionLocal()
    try:
        from models import RiskEvent
        
        # 获取未解决的风险事件
        events = db.query(RiskEvent).filter(
            RiskEvent.ad_account_id == account_id,
            RiskEvent.is_resolved == False
        ).order_by(RiskEvent.created_at.desc()).limit(10).all()
        
        if not events:
            return {"status": "no_events"}
        
        notifier = NotificationService()
        message = f"检测到 {len(events)} 个风险事件\n"
        for event in events:
            message += f"- [{event.risk_level.value}] {event.title}\n"
        
        notifier.notify_all(f"广告账户 {account_id} 风险告警", message)
        
        logger.info(f"Risk notifications sent for {account_id}")
        return {"status": "sent", "events_count": len(events)}
    except Exception as exc:
        logger.error(f"Failed to send risk notifications: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@shared_task(bind=True, max_retries=1)
def notify_daily_report(self, account_id: str, report_date: str) -> Dict:
    """发送日报告通知"""
    try:
        notifier = NotificationService()
        message = f"账户 {account_id} 的 {report_date} 日报告已生成"
        notifier.notify_all("日报告已生成", message)
        
        logger.info(f"Daily report notification sent for {account_id}")
        return {"status": "sent"}
    except Exception as exc:
        logger.error(f"Failed to send daily report notification: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)

@shared_task(bind=True, max_retries=1)
def notify_weekly_report(self, account_id: str) -> Dict:
    """发送周报告通知"""
    try:
        notifier = NotificationService()
        message = f"账户 {account_id} 的本周周报告已生成"
        notifier.notify_all("周报告已生成", message)
        
        logger.info(f"Weekly report notification sent for {account_id}")
        return {"status": "sent"}
    except Exception as exc:
        logger.error(f"Failed to send weekly report notification: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


# ==================== 定时编排任务（由 Celery Beat 触发） ====================
# 设计文档第 5 / 24 节：定时任务统一由 Celery Beat 负责。
# Beat 只能触发无参任务，因此「遍历账户再逐个派发」的逻辑下沉为编排任务。

@shared_task(bind=True, name="tasks.celery_tasks.dispatch_daily_reports")
def dispatch_daily_reports(self) -> Dict:
    """日报告编排：为所有活跃账户派发生成任务"""
    db = SessionLocal()
    try:
        from models import AdAccount

        # 只处理系统侧允许参与投放的账户（历史上这里用的 is_active 列并不存在，
        # 导致定时任务每次都抛错、实际一次都没跑起来）
        accounts = (
            db.query(AdAccount)
            .filter(AdAccount.system_status == SystemStatus.ACTIVE.value)
            .all()
        )
        for account in accounts:
            generate_daily_report.apply_async(args=(account.account_id,), countdown=5)

        logger.info(f"Dispatched daily reports for {len(accounts)} accounts")
        return {"status": "dispatched", "accounts": len(accounts)}
    except Exception as exc:
        logger.error(f"Failed to dispatch daily reports: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(bind=True, name="tasks.celery_tasks.dispatch_weekly_reports")
def dispatch_weekly_reports(self) -> Dict:
    """周报告编排：为所有活跃账户派发生成任务"""
    db = SessionLocal()
    try:
        from models import AdAccount

        # 只处理系统侧允许参与投放的账户（历史上这里用的 is_active 列并不存在，
        # 导致定时任务每次都抛错、实际一次都没跑起来）
        accounts = (
            db.query(AdAccount)
            .filter(AdAccount.system_status == SystemStatus.ACTIVE.value)
            .all()
        )
        for account in accounts:
            generate_weekly_report.apply_async(args=(account.account_id,), countdown=5)

        logger.info(f"Dispatched weekly reports for {len(accounts)} accounts")
        return {"status": "dispatched", "accounts": len(accounts)}
    except Exception as exc:
        logger.error(f"Failed to dispatch weekly reports: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
