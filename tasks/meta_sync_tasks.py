"""Meta 同步的 Celery 任务（Meta 账号管理 V1 —— 文档 §25）

设计原则：
    HTTP 不应该长时间等待 Meta API。

    HTTP → 创建 Sync Job（meta_sync_logs）→ 投递 Celery → 立即返回 job_id
                                              ↓
                                        Worker 调 Meta API → 写库 → 更新日志

注册提醒：
    新任务模块必须在 celery_app.py 中显式导入。autodiscover_tasks(['tasks'])
    只导入 tasks 包本身，不会递归子模块，漏了会报
    "Received unregistered task of type 'meta.sync_ad_accounts'"。
"""
from typing import Dict

from celery import shared_task

from core.database import SessionLocal
from core.logger import logger
from core.tenant import for_all_tenants, resolve_tenant_of, tenant_task
from models import AdAccount, MetaAccount
from services.ad_account_resolver import resolve_tenant_of_ad_account_ref
from services.ads_manager import AdsManager
from services.meta import MetaSyncService


def _log_to_dict(log) -> Dict:
    return log.to_dict() if log else {}


# 注意：任务参数名 `business_id` 沿用了历史签名，实际传的是 MetaAccount 的主键 id
# （api/meta_accounts.py 传 meta.id），而不是 Meta 侧的 Business ID 列。
# resolver 因此显式指定 column="id"，避免与 MetaAccount.business_id 列混淆。


@shared_task(bind=True, name="meta.sync_ad_accounts", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, business_id: resolve_tenant_of(MetaAccount, business_id, column="id"))
def sync_ad_accounts_task(self, business_id: str) -> Dict:
    """同步某个 BM 下的全部广告账户"""
    db = SessionLocal()
    try:
        service = MetaSyncService(db)
        log = service.sync_ad_accounts(business_id)
        logger.info(
            f"[meta_sync] BM {business_id} 账户同步完成: "
            f"{log.status} ({log.success_count}/{log.total_count})"
        )
        return {"status": "success", "sync_log": _log_to_dict(log)}
    except Exception as exc:
        logger.error(f"[meta_sync] BM {business_id} 账户同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_business", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, business_id: resolve_tenant_of(MetaAccount, business_id, column="id"))
def sync_business_task(self, business_id: str) -> Dict:
    """同步某个 BM 的基础信息"""
    db = SessionLocal()
    try:
        log = MetaSyncService(db).sync_business(business_id)
        return {"status": "success", "sync_log": _log_to_dict(log)}
    except Exception as exc:
        logger.error(f"[meta_sync] BM {business_id} 信息同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_ad_account", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, ad_account_id: resolve_tenant_of(AdAccount, ad_account_id))
def sync_ad_account_task(self, ad_account_id: str) -> Dict:
    """同步单个广告账户的 Meta 侧信息"""
    db = SessionLocal()
    try:
        log = MetaSyncService(db).sync_ad_account(ad_account_id)
        return {"status": "success", "sync_log": _log_to_dict(log)}
    except Exception as exc:
        logger.error(f"[meta_sync] 账户 {ad_account_id} 同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_campaigns", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, account_id: resolve_tenant_of_ad_account_ref(account_id))
def sync_campaigns_task(self, account_id: str) -> Dict:
    """同步某个广告账户下的广告系列（Campaign）

    此前 `POST /accounts/{id}/sync-campaigns` 是同步执行、HTTP 直等 Meta API，
    账户多或网络慢时会拖垮请求线程。改为异步后 HTTP 只负责投递任务。

    Args:
        account_id: 广告账户主键，兼容 Meta 账户号 act_xxx
    """
    db = SessionLocal()
    try:
        created, updated = AdsManager(db).sync_campaigns(account_id)
        logger.info(
            f"[meta_sync] 账户 {account_id} 系列同步完成: 新增 {created} 更新 {updated}"
        )
        return {
            "status": "success",
            "account_id": account_id,
            "created": created,
            "updated": updated,
        }
    except Exception as exc:
        logger.error(f"[meta_sync] 账户 {account_id} 系列同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_all_businesses")
@for_all_tenants
def sync_all_businesses_task(self) -> Dict:
    """同步全部启用中的 BM（可由 Beat 定时触发）"""
    db = SessionLocal()
    try:
        businesses = (
            db.query(MetaAccount)
            .filter(MetaAccount.status == "ACTIVE")
            .all()
        )
        submitted = []
        for business in businesses:
            result = sync_ad_accounts_task.apply_async(
                args=[business.id], countdown=5 * len(submitted)
            )
            submitted.append({"business_id": business.id, "task_id": result.id})

        logger.info(f"[meta_sync] 提交 {len(submitted)} 个 BM 的同步任务")
        return {"status": "submitted", "count": len(submitted), "tasks": submitted}
    finally:
        db.close()
