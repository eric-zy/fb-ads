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
from models import AdAccount, MetaAccount, CampaignInstance, AdSetInstance, AdInstance
from services.ad_account_resolver import resolve_tenant_of_ad_account_ref
from services.ads_manager import AdsManager
from services.meta import MetaSyncService
from services.credential_service import CredentialService


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


@shared_task(bind=True, name="meta.sync_delivery_objects", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, account_id: resolve_tenant_of_ad_account_ref(account_id))
def sync_delivery_objects_task(self, account_id: str) -> Dict:
    """异步同步本地 Campaign / AdSet / Ad 的 Meta 状态。"""
    db = SessionLocal()
    try:
        account = db.query(AdAccount).filter(
            (AdAccount.id == account_id) | (AdAccount.account_id == account_id)
        ).first()
        if not account:
            return {"status": "failed", "error": "广告账户不存在"}
        service = CredentialService(db).build_service(account.id)
        campaigns = db.query(CampaignInstance).filter(CampaignInstance.ad_account_id == account.id).all()
        # 每个账户只拉取一次，避免按 Campaign / AdSet 重复请求 Meta API。
        sync_errors = []
        try:
            remote_campaigns = service.list_campaigns(account.account_id)
        except Exception as exc:
            logger.warning(f"[meta_sync] 账户 {account.id} Campaign 拉取失败: {exc}")
            remote_campaigns = []
            sync_errors.append({"type": "CAMPAIGN", "error": str(exc)})
        remote_campaign_by_id = {str(item.get("id")): item for item in remote_campaigns}
        remote_adsets_by_campaign = {}
        remote_ads_by_adset = {}
        updated = 0
        for campaign in campaigns:
            remote = remote_campaign_by_id.get(str(campaign.meta_campaign_id))
            if remote:
                campaign.meta_status = remote.get("effective_status") or remote.get("status")
                campaign.status = remote.get("status") or campaign.status
                updated += 1
            for adset in campaign.adsets:
                if adset.meta_adset_id:
                    campaign_key = str(campaign.meta_campaign_id)
                    if campaign_key not in remote_adsets_by_campaign:
                        try:
                            remote_adsets_by_campaign[campaign_key] = service.list_adsets(campaign.meta_campaign_id)
                        except Exception as exc:
                            logger.warning(f"[meta_sync] Campaign {campaign_key} AdSet 拉取失败: {exc}")
                            remote_adsets_by_campaign[campaign_key] = []
                            sync_errors.append({"type": "ADSET", "parent_id": campaign_key, "error": str(exc)})
                    remote_set_by_id = {str(item.get("id")): item for item in remote_adsets_by_campaign[campaign_key]}
                    remote_set = remote_set_by_id.get(str(adset.meta_adset_id))
                    if remote_set:
                        adset.status = remote_set.get("effective_status") or remote_set.get("status") or adset.status
                        updated += 1
                for ad in adset.ads:
                    if ad.meta_ad_id:
                        adset_key = str(adset.meta_adset_id)
                        if adset_key not in remote_ads_by_adset:
                            try:
                                remote_ads_by_adset[adset_key] = service.list_ads(adset.meta_adset_id)
                            except Exception as exc:
                                logger.warning(f"[meta_sync] AdSet {adset_key} Ad 拉取失败: {exc}")
                                remote_ads_by_adset[adset_key] = []
                                sync_errors.append({"type": "AD", "parent_id": adset_key, "error": str(exc)})
                        remote_ad_by_id = {str(item.get("id")): item for item in remote_ads_by_adset[adset_key]}
                        remote_ad = remote_ad_by_id.get(str(ad.meta_ad_id))
                        if remote_ad:
                            ad.status = remote_ad.get("effective_status") or remote_ad.get("status") or ad.status
                            updated += 1
        db.commit()
        return {
            "status": "partial_success" if sync_errors else "success",
            "account_id": account.id,
            "updated": updated,
            "error_count": len(sync_errors),
            "errors": sync_errors[:20],
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[meta_sync] 投放对象同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.update_delivery_object", max_retries=2, default_retry_delay=30)
@tenant_task(lambda self, object_type, object_id, account_id, action: resolve_tenant_of(AdAccount, account_id))
def update_delivery_object_task(self, object_type: str, object_id: str, account_id: str, action: str) -> Dict:
    """异步暂停/启用单个 AdSet 或 Ad。"""
    db = SessionLocal()
    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return {"status": "failed", "error": "广告账户不存在"}
        service = CredentialService(db).build_service(account.id)
        remote_status = "PAUSED" if action == "PAUSE" else "ACTIVE"
        if object_type == "ADSET":
            obj = db.query(AdSetInstance).filter(AdSetInstance.id == object_id).first()
            if not obj or not obj.meta_adset_id:
                raise RuntimeError("广告组 Meta ID 不存在")
            service.update_adset(obj.meta_adset_id, {"status": remote_status})
            obj.status = remote_status
        elif object_type == "AD":
            obj = db.query(AdInstance).filter(AdInstance.id == object_id).first()
            if not obj or not obj.meta_ad_id:
                raise RuntimeError("广告 Meta ID 不存在")
            service.update_ad(obj.meta_ad_id, {"status": remote_status})
            obj.status = remote_status
        else:
            raise RuntimeError("不支持的投放对象类型")
        db.commit()
        return {"status": "success", "object_type": object_type, "object_id": object_id, "state": remote_status}
    except Exception as exc:
        db.rollback()
        logger.error(f"[meta] {object_type} {object_id} 操作失败: {exc}")
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
