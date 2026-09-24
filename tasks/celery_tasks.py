"""Celery异步任务定义"""
from celery import shared_task
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.logger import logger
from core.redis_client import redis_client
from core.tenant import for_all_tenants, resolve_tenant_of, tenant_task
from config.settings import settings
from models import AdAccount, RiskExecution, Tenant
from services.ads_manager import AdsManager
from services.risk_detector import RiskDetector
from services.analytics import AnalyticsEngine
from services.notifications import NotificationService
from services.risk_action_service import retry_failed_execution, run_account_rules
from services.risk_reliability import (
    check_database,
    log_dependency_failure,
    resolve_operational_alerts,
    upsert_operational_alert,
)


def _resolve_account_tenant(account_id: str) -> Optional[str]:
    """Celery 风控任务按账户建立租户上下文。"""
    return resolve_tenant_of(AdAccount, account_id)


# ==================== 洞察数据采集 ====================

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
@tenant_task(lambda self, account_id, days=3: resolve_tenant_of(AdAccount, account_id))
def fetch_account_insights(self, account_id: str, days: int = 3) -> Dict:
    """拉取账户洞察数据
    
    Args:
        account_id: 广告账户ID
        days: 采集天数，默认最近3天；用于覆盖 Meta 延迟归因和修正数据
    
    Returns:
        采集结果统计
    """
    db = SessionLocal()
    lock = None
    lock_acquired = False
    try:
        # 同一账户的洞察任务必须串行。Meta 报表通常需要几十秒到数分钟，
        # 旧任务重试或用户手动补跑时如果并发执行，会互相竞争同一批
        # (entity, date) 主键并产生重复键，同时放大 Meta API 限流。
        lock_key = f"fbads:insights-sync:{account_id}"
        try:
            lock = redis_client.redis_client.lock(
                lock_key,
                timeout=max(int(settings.FB_CONNECTOR_REPORT_TIMEOUT) * 3, 1800),
                blocking=False,
            )
            if not lock.acquire(blocking=False):
                logger.warning("Insights sync already running for account %s", account_id)
                return {
                    "status": "skipped",
                    "account_id": account_id,
                    "reason": "same_account_task_running",
                }
            lock_acquired = True
        except Exception as lock_exc:
            # 锁服务不可用时不能放任任务并发写报表；让 Celery 稍后重试。
            logger.error("Failed to acquire insights sync lock for %s: %s", account_id, lock_exc)
            raise lock_exc

        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            logger.warning("[Insights] 账户不存在，跳过同步: %s", account_id)
            return {"status": "skipped", "account_id": account_id, "reason": "account_not_found"}

        # 即使 Meta 返回空报表，也要让页面知道任务正在执行。
        account.insights_sync_status = "SYNCING"
        account.insights_last_sync_error = None
        db.commit()

        logger.info(f"Fetching insights for account {account_id}")

        ads_manager = AdsManager(db)
        # days 表示包含今天在内的自然日数量。
        start_date = (date.today() - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        end_date = date.today().strftime('%Y-%m-%d')
        
        insights_count = ads_manager.fetch_insights(account_id, start_date, end_date)
        delivery_counts = ads_manager.fetch_delivery_insights(account_id, start_date, end_date)

        # 不能用 insights_count 判断成功：无消耗账户可能合法返回 0 行。
        account.insights_sync_status = "SUCCESS"
        account.insights_last_synced_at = datetime.utcnow()
        account.insights_last_sync_error = None
        db.commit()

        logger.info(f"Successfully fetched {insights_count} insights for {account_id}")
        return {
            "status": "success",
            "account_id": account_id,
            "insights_count": insights_count,
            "delivery_counts": delivery_counts,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to fetch insights for {account_id}: {str(exc)}")
        try:
            db.rollback()
            account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
            if account:
                account.insights_sync_status = "FAILED"
                account.insights_last_sync_error = str(exc)[:2000]
                db.commit()
        except Exception:
            db.rollback()
        # 重试
        raise self.retry(exc=exc, countdown=60)
    finally:
        if lock is not None and lock_acquired:
            try:
                lock.release()
            except Exception:
                logger.warning("Failed to release insights sync lock for %s", account_id)
        db.close()

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
@for_all_tenants
def fetch_all_accounts_insights(self, days: int = 3) -> Dict:
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
                    args=(account.id, days),
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
@tenant_task(lambda self, account_id: _resolve_account_tenant(account_id))
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
        
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return {"status": "not_found", "account_id": account_id}

        # RC-04：每轮重新读取本地指标、重新求值，再由动作服务执行。
        # 旧 RiskDetector 保留供历史手动调用，但不再由定时任务直接触发。
        results = run_account_rules(db, account)
        
        logger.info(f"Risk check completed for {account_id}: {results}")
        
        # 如果有风险，发送通知
        if results.get("counts", {}).get("success", 0) > 0:
            notify_risk_events.delay(account_id)
        
        return {
            "status": "partial" if results.get("counts", {}).get("failed", 0) > 0 else "success",
            "account_id": account_id,
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to check risk for {account_id}: {str(exc)}")
        try:
            # 风控执行异常可能已经让当前事务进入 failed 状态，
            # 先回滚再查询和写入运营告警，避免告警也被同一事务拖垮。
            db.rollback()
            account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
            if account:
                alert, created = upsert_operational_alert(
                    db,
                    tenant_id=account.tenant_id,
                    ad_account_id=account.id,
                    alert_type="RISK_WORKER_FAILED",
                    title="风控 Worker 执行失败",
                    message=f"账户 {account_id} 的风控任务失败：{str(exc)[:500]}",
                )
                if created:
                    NotificationService().notify_all(alert.title, alert.message)
        except Exception:
            logger.exception("Failed to persist risk worker failure alert for %s", account_id)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@shared_task(bind=True, max_retries=2)
@for_all_tenants
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
                    args=(account.id,),
                    countdown=3
                )
                results.append(result.id)
            except Exception as e:
                logger.error(f"Failed to submit risk check for {account.account_id}: {str(e)}")
        
        logger.info(f"Submitted {len(results)} risk check tasks")
        return {"status": "submitted", "task_count": len(results)}
    finally:
        db.close()


@shared_task(bind=True, max_retries=1, name="tasks.celery_tasks.monitor_risk_dependencies")
@for_all_tenants
def monitor_risk_dependencies(self) -> Dict:
    """巡检风控依赖；告警按租户和依赖类型去重，恢复后自动关闭。"""
    db = SessionLocal()
    try:
        check_database(db)
        redis_ok = True
        try:
            redis_client.redis_client.ping()
        except Exception as exc:
            redis_ok = False
            log_dependency_failure("redis", exc)

        tenants = db.query(Tenant).all()
        if redis_ok:
            for tenant in tenants:
                resolve_operational_alerts(db, tenant_id=tenant.id, alert_type="RISK_REDIS_UNAVAILABLE")
        else:
            for tenant in tenants:
                alert, created = upsert_operational_alert(
                    db,
                    tenant_id=tenant.id,
                    alert_type="RISK_REDIS_UNAVAILABLE",
                    title="风控依赖 Redis 不可用",
                    message="风控任务依赖的 Redis ping 失败，请检查 Redis 服务、连接地址和网络。",
                )
                if created:
                    NotificationService().notify_all(alert.title, alert.message)
        return {"status": "ok" if redis_ok else "degraded", "redis": redis_ok, "tenants": len(tenants)}
    except Exception as exc:
        # 数据库本身不可用时无法安全写告警，保留日志并让 Beat/监控系统接管。
        log_dependency_failure("database", exc)
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(bind=True, max_retries=2, default_retry_delay=120, name="risk.retry_execution")
@tenant_task(lambda self, execution_id: resolve_tenant_of(RiskExecution, execution_id))
def retry_risk_execution(self, execution_id: str) -> Dict:
    """显式重试失败的风控动作；不会跳过规则二次校验。"""
    db = SessionLocal()
    try:
        execution = db.query(RiskExecution).filter(RiskExecution.id == execution_id).first()
        if not execution:
            return {"status": "not_found", "execution_id": execution_id}
        if execution.status != "FAILED":
            return {"status": "ignored", "execution_id": execution_id, "reason": "仅允许重试 FAILED 记录"}
        result = retry_failed_execution(db, execution)
        return {
            "status": "success" if result.status == "SUCCESS" else result.status.lower(),
            "execution_id": execution_id,
            "execution_status": result.status,
            "retry_count": result.retry_count,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to retry risk execution %s", execution_id)
        raise self.retry(exc=exc, countdown=120)
    finally:
        db.close()

# ==================== 报告生成 ====================

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
@tenant_task(lambda self, account_id, report_date=None: _resolve_account_tenant(account_id))
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
@tenant_task(lambda self, account_id: _resolve_account_tenant(account_id))
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
@tenant_task(lambda self, account_id: _resolve_account_tenant(account_id))
def notify_risk_events(self, account_id: str) -> Dict:
    """发送风险事件通知"""
    db = SessionLocal()
    try:
        from models import RiskEvent
        
        # 获取未解决的风险事件
        from sqlalchemy import or_
        events = db.query(RiskEvent).filter(
            RiskEvent.ad_account_id == account_id,
            RiskEvent.is_resolved == False,
            or_(
                RiskEvent.notification_status.is_(None),
                ~RiskEvent.notification_status.in_(["SENT", "SKIPPED"]),
            ),
        ).order_by(RiskEvent.created_at.desc()).limit(10).all()
        
        if not events:
            return {"status": "no_events"}
        
        notifier = NotificationService()
        configured_channels = [
            name for name, enabled in (
                ("email", notifier.email_enabled),
                ("dingtalk", notifier.dingtalk_enabled),
                ("slack", notifier.slack_enabled),
            ) if enabled
        ]
        results = {}
        has_failure = False
        now = datetime.utcnow()
        for event in events:
            previous = dict(event.notification_results or {})
            pending_channels = [
                channel for channel in configured_channels
                if previous.get(channel) != "success"
            ]
            if pending_channels:
                message = f"[{event.risk_level.value}] {event.title}\n{event.description or ''}"
                channel_results = notifier.notify_all(
                    f"广告账户 {account_id} 风险告警",
                    message,
                    channels=pending_channels,
                )
                previous.update(channel_results)
                results.update(channel_results)
            remaining_failures = [
                channel for channel in configured_channels
                if previous.get(channel) != "success"
            ]
            event.notification_attempts = int(event.notification_attempts or 0) + 1
            event.notification_results = previous
            if not configured_channels:
                event.notification_status = "SKIPPED"
                event.notification_error = "未启用任何通知渠道"
            elif remaining_failures:
                event.notification_status = "FAILED"
                event.notification_error = str({channel: previous.get(channel) for channel in remaining_failures})[:1000]
                has_failure = True
            else:
                event.notification_status = "SENT"
                event.notification_sent_at = now
                event.notification_error = None
        db.commit()

        if has_failure:
            raise RuntimeError(f"风险告警通知部分失败: {results}")
        
        logger.info(f"Risk notifications sent for {account_id}")
        return {"status": "sent" if results else "skipped", "events_count": len(events), "channels": results}
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
@for_all_tenants
def dispatch_daily_reports(self) -> Dict:
    """日报告编排：为所有活跃账户派发生成任务"""
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
        for account in accounts:
            generate_daily_report.apply_async(args=(account.id,), countdown=5)

        logger.info(f"Dispatched daily reports for {len(accounts)} accounts")
        return {"status": "dispatched", "accounts": len(accounts)}
    except Exception as exc:
        logger.error(f"Failed to dispatch daily reports: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@shared_task(bind=True, name="tasks.celery_tasks.dispatch_weekly_reports")
@for_all_tenants
def dispatch_weekly_reports(self) -> Dict:
    """周报告编排：为所有活跃账户派发生成任务"""
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
        for account in accounts:
            generate_weekly_report.apply_async(args=(account.id,), countdown=5)

        logger.info(f"Dispatched weekly reports for {len(accounts)} accounts")
        return {"status": "dispatched", "accounts": len(accounts)}
    except Exception as exc:
        logger.error(f"Failed to dispatch weekly reports: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
