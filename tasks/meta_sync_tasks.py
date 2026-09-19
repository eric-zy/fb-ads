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
from datetime import datetime
from typing import Dict

from celery import shared_task

from config.settings import settings
from core.database import SessionLocal
from core.logger import logger
from core.tenant import for_all_tenants, resolve_tenant_of, tenant_task, bypass_tenant
from models import AdAccount, MetaAccount, CampaignInstance, AdSetInstance, AdInstance, Credential, DeliveryAction, SyncAlert
import uuid
from services.ads_manager import AdsManager
from services.meta import MetaSyncService
from services.meta.page_service import MetaPageSyncService
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from services.notifications import NotificationService
from services.account_dispatch import AccountDispatchService
from services.meta.connector_page_sync import sync_connector_pages


def _log_to_dict(log) -> Dict:
    return log.to_dict() if log else {}


@shared_task(bind=True, name="meta.sync_pages", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, credential_id: resolve_tenant_of(Credential, credential_id))
def sync_meta_pages_task(self, credential_id: str) -> Dict:
    """按凭据同步该租户可管理的 Facebook Pages。"""
    if settings.FB_ACCESS_MODE == "connector":
        return {"status": "skipped", "credential_id": credential_id, "reason": "connector 页面同步走 API Connector"}
    db = SessionLocal()
    try:
        credential = db.query(Credential).filter(Credential.id == credential_id).first()
        return {"status": "success", **MetaPageSyncService(db).sync_credential(credential_id)}
    except Exception as exc:
        db.rollback()
        credential = db.query(Credential).filter(Credential.id == credential_id).first()
        logger.error(f"[meta_pages] {_credential_label(credential, credential_id)} 页面同步失败: {exc}")
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "credential_id": credential_id, "error": str(exc)}
    finally:
        db.close()


def _credential_label(credential: Credential, credential_id: str) -> str:
    """返回可安全写入日志的凭据归属信息，不包含 Access Token。"""
    if not credential:
        return f"凭据 {credential_id}"
    bm = getattr(credential, "meta_account", None)
    bm_name = getattr(bm, "name", None) if bm else None
    bm_id = getattr(bm, "business_id", None) if bm else None
    parts = [
        f"凭据 {credential.id}",
        f"账号名={credential.name or '未命名'}",
        f"Meta用户ID={credential.meta_user_id or '未知'}",
    ]
    if bm_name or bm_id:
        parts.append(f"BM={bm_name or '未命名'}({bm_id or bm.id})")
    return " ".join(parts)


@shared_task(bind=True, name="meta.sync_all_pages")
@for_all_tenants
def sync_all_meta_pages_task(self) -> Dict:
    """定时巡检所有租户的有效 OAuth 凭据。"""
    if settings.FB_ACCESS_MODE == "connector":
        return {"status": "skipped", "reason": "connector 页面同步不扫描国内 Credential 表"}
    db = SessionLocal()
    submitted = []
    try:
        with bypass_tenant():
            credentials = db.query(Credential).filter(
                Credential.source == "OAUTH",
                Credential.status == "ACTIVE",
            ).all()
            for credential in credentials:
                submitted.append(sync_meta_pages_task.delay(credential.id).id)
        return {"status": "queued", "count": len(submitted), "task_ids": submitted}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_authorization")
@tenant_task(lambda self, credential_id: resolve_tenant_of(Credential, credential_id))
def sync_meta_authorization_task(self, credential_id: str) -> Dict:
    """XMP 式一次授权后的统一资产同步入口：BM、广告账户、Facebook Page。"""
    if settings.FB_ACCESS_MODE == "connector":
        return {"status": "skipped", "credential_id": credential_id, "reason": "connector OAuth 在海外完成资产同步"}
    db = SessionLocal()
    try:
        credential = db.query(Credential).filter(Credential.id == credential_id).first()
        if not credential or not credential.meta_account_id:
            return {"status": "failed", "error": "OAuth 凭据尚未绑定 BM"}
        business_id = credential.meta_account_id
        business_task = sync_business_task.delay(business_id)
        account_task = sync_ad_accounts_task.delay(business_id)
        page_task = sync_meta_pages_task.delay(credential_id)
        return {
            "status": "queued",
            "credential_id": credential_id,
            "business_id": business_id,
            "task_ids": {
                "business": business_task.id,
                "ad_accounts": account_task.id,
                "pages": page_task.id,
            },
        }
    finally:
        db.close()


# 注意：任务参数名 `business_id` 沿用了历史签名，实际传的是 MetaAccount 的主键 id
# （api/meta_accounts.py 传 meta.id），而不是 Meta 侧的 Business ID 列。
# resolver 因此显式指定 column="id"，避免与 MetaAccount.business_id 列混淆。


@shared_task(bind=True, name="meta.sync_ad_accounts", max_retries=2, default_retry_delay=60)
@tenant_task(lambda self, business_id: resolve_tenant_of(MetaAccount, business_id, column="id"))
def sync_ad_accounts_task(self, business_id: str) -> Dict:
    """同步某个 BM 下的全部广告账户，并刷新其 Facebook Page。"""
    db = SessionLocal()
    try:
        service = MetaSyncService(db)
        log = service.sync_ad_accounts(business_id)
        logger.info(
            f"[meta_sync] BM {business_id} 账户同步完成: "
            f"{log.status} ({log.success_count}/{log.total_count})"
        )
        business = db.query(MetaAccount).filter(MetaAccount.id == business_id).first()
        page_sync = {"status": "SKIPPED", "count": 0, "page_ids": []}
        if settings.FB_ACCESS_MODE == "connector" and business and business.connector_credential_id:
            try:
                page_sync = {
                    "status": "SUCCESS",
                    **sync_connector_pages(
                        db,
                        business.tenant_id,
                        business.connector_credential_id,
                    ),
                }
                db.commit()
            except FBConnectorError as exc:
                db.rollback()
                logger.warning(
                    f"[meta_sync] BM {business_id} Page 同步失败（账户同步已完成）: {exc}"
                )
                page_sync = {
                    "status": "FAILED",
                    "credential_id": business.connector_credential_id,
                    "count": 0,
                    "page_ids": [],
                    "error": str(exc),
                }
        # OAuth 导入/定时同步完成后，自动把新账户交给 SaaS 分配规则。
        # 同步成功不应因“尚未配置分配规则”而失败，因此分配结果单独返回。
        assignment = AccountDispatchService(db).dispatch_unassigned(
            tenant_id=business.tenant_id if business else None,
            operator_id=None,
        )
        return {
            "status": "success",
            "sync_log": _log_to_dict(log),
            "page_sync": page_sync,
            "assignment": assignment,
        }
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
@tenant_task(lambda self, account_id: resolve_tenant_of(AdAccount, account_id))
def sync_campaigns_task(self, account_id: str) -> Dict:
    """同步某个广告账户下的广告系列（Campaign）

    此前 `POST /accounts/{id}/sync-campaigns` 是同步执行、HTTP 直等 Meta API，
    账户多或网络慢时会拖垮请求线程。改为异步后 HTTP 只负责投递任务。

    Args:
        account_id: 广告账户内部主键
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
@tenant_task(lambda self, account_id: resolve_tenant_of(AdAccount, account_id))
def sync_delivery_objects_task(self, account_id: str) -> Dict:
    """异步同步本地 Campaign / AdSet / Ad 的 Meta 状态。"""
    db = SessionLocal()
    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return {"status": "failed", "error": "广告账户不存在"}
        ref = CredentialResolver(db).for_account(account.id)
        campaigns = db.query(CampaignInstance).filter(CampaignInstance.ad_account_id == account.id).all()
        # 每个账户只拉取一次，避免按 Campaign / AdSet 重复请求 Meta API。
        sync_errors = []
        campaign_fetch_ok = True
        try:
            remote_campaigns = FBConnectorClient().list_campaigns(
                account.account_id, ref.credential_id
            ).get("campaigns", [])
        except Exception as exc:
            logger.warning(f"[meta_sync] 账户 {account.id} Campaign 拉取失败: {exc}")
            campaign_fetch_ok = False
            remote_campaigns = []
            sync_errors.append({"type": "CAMPAIGN", "error": str(exc)})
        remote_campaign_by_id = {str(item.get("id")): item for item in remote_campaigns}
        remote_adsets_by_campaign = {}
        remote_ads_by_adset = {}
        updated = 0

        def sync_instance_state(instance, remote, object_type: str, object_id: str) -> int:
            """同步远端状态，同时保留本地归档/删除语义并记录漂移。"""
            now = datetime.utcnow()
            if remote is None:
                instance.meta_status = "NOT_FOUND"
                instance.last_synced_at = now
                if instance.last_error != "REMOTE_NOT_FOUND":
                    sync_errors.append({
                        "type": object_type,
                        "object_id": object_id,
                        "error": "REMOTE_NOT_FOUND",
                    })
                instance.last_error = "REMOTE_NOT_FOUND"
                return 0

            remote_status = remote.get("status") or remote.get("effective_status")
            instance.meta_status = remote.get("effective_status") or remote_status
            if instance.status not in {"ARCHIVED", "DELETED"}:
                instance.status = remote_status or instance.status
            instance.last_synced_at = now

            expected_remote = instance.desired_status
            if expected_remote in {"ARCHIVED", "DELETED"}:
                expected_remote = "PAUSED"
            drift = bool(expected_remote and remote_status and remote_status != expected_remote)
            next_error = f"REMOTE_STATUS_DRIFT:{remote_status}" if drift else None
            if next_error and next_error != instance.last_error:
                sync_errors.append({
                    "type": object_type,
                    "object_id": object_id,
                    "error": next_error,
                })
            instance.last_error = next_error
            return 1

        for campaign in campaigns:
            remote = remote_campaign_by_id.get(str(campaign.meta_campaign_id))
            if campaign_fetch_ok and campaign.meta_campaign_id:
                updated += sync_instance_state(campaign, remote, "CAMPAIGN", str(campaign.id))
            for adset in campaign.adsets:
                if adset.meta_adset_id:
                    campaign_key = str(campaign.meta_campaign_id)
                    if campaign_key not in remote_adsets_by_campaign:
                        try:
                            remote_adsets_by_campaign[campaign_key] = FBConnectorClient().list_adsets(
                                campaign.meta_campaign_id, ref.credential_id
                            ).get("adsets", [])
                        except Exception as exc:
                            logger.warning(f"[meta_sync] Campaign {campaign_key} AdSet 拉取失败: {exc}")
                            remote_adsets_by_campaign[campaign_key] = None
                            sync_errors.append({"type": "ADSET", "parent_id": campaign_key, "error": str(exc)})
                    remote_sets = remote_adsets_by_campaign[campaign_key]
                    if remote_sets is not None:
                        remote_set_by_id = {str(item.get("id")): item for item in remote_sets}
                        remote_set = remote_set_by_id.get(str(adset.meta_adset_id))
                        updated += sync_instance_state(adset, remote_set, "ADSET", str(adset.id))
                for ad in adset.ads:
                    if ad.meta_ad_id:
                        adset_key = str(adset.meta_adset_id)
                        if adset_key not in remote_ads_by_adset:
                            try:
                                remote_ads_by_adset[adset_key] = FBConnectorClient().list_ads(
                                    adset.meta_adset_id, ref.credential_id
                                ).get("ads", [])
                            except Exception as exc:
                                logger.warning(f"[meta_sync] AdSet {adset_key} Ad 拉取失败: {exc}")
                                remote_ads_by_adset[adset_key] = None
                                sync_errors.append({"type": "AD", "parent_id": adset_key, "error": str(exc)})
                        remote_ads = remote_ads_by_adset[adset_key]
                        if remote_ads is not None:
                            remote_ad_by_id = {str(item.get("id")): item for item in remote_ads}
                            remote_ad = remote_ad_by_id.get(str(ad.meta_ad_id))
                            updated += sync_instance_state(ad, remote_ad, "AD", str(ad.id))
        db.commit()
        if sync_errors:
            alert_message = str(sync_errors[:20])
            alert = db.query(SyncAlert).filter(
                SyncAlert.tenant_id == account.tenant_id,
                SyncAlert.ad_account_id == account.id,
                SyncAlert.alert_type == "DELIVERY_SYNC",
                SyncAlert.is_resolved.is_(False),
            ).first()
            is_new_alert = alert is None
            if alert:
                alert.message = alert_message
            else:
                db.add(SyncAlert(id=uuid.uuid4().hex, tenant_id=account.tenant_id, ad_account_id=account.id,
                                 alert_type="DELIVERY_SYNC", title="Meta 投放状态同步异常",
                                 message=alert_message))
            db.commit()
            if is_new_alert:
                try:
                    NotificationService().notify_all(
                        "Meta 投放状态同步异常",
                        f"广告账户 {account.account_id} 同步存在 {len(sync_errors)} 项异常：{sync_errors[0].get('error', '未知错误')}",
                    )
                except Exception:
                    logger.exception("[meta_sync] 投放状态同步告警发送失败")
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
            account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
            if account:
                db.add(SyncAlert(id=uuid.uuid4().hex, tenant_id=account.tenant_id, ad_account_id=account.id,
                                 alert_type="DELIVERY_SYNC_FAILED", title="Meta 投放状态同步失败", message=str(exc)))
                db.commit()
            try:
                NotificationService().notify_all("Meta 投放状态同步失败", f"广告账户 {account_id} 同步失败：{exc}")
            except Exception:
                logger.exception("[meta_sync] 投放状态同步失败告警发送失败")
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.sync_all_delivery_objects")
@for_all_tenants
def sync_all_delivery_objects_task(self) -> Dict:
    """由 Celery Beat 定期同步所有已有本地投放记录的广告账户。"""
    db = SessionLocal()
    try:
        with bypass_tenant():
            account_ids = [row.ad_account_id for row in db.query(CampaignInstance.ad_account_id).distinct().all()]
        task_ids = [sync_delivery_objects_task.delay(account_id).id for account_id in account_ids]
        return {"status": "queued", "account_count": len(account_ids), "task_ids": task_ids}
    except Exception as exc:
        logger.exception(f"[meta_sync] 定时投放状态同步派发失败: {exc}")
        try:
            NotificationService().notify_all("Meta 投放状态同步告警", f"定时同步任务派发失败：{exc}")
        except Exception:
            logger.exception("[meta_sync] 同步告警发送失败")
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


@shared_task(bind=True, name="meta.update_delivery_object", max_retries=2, default_retry_delay=30)
@tenant_task(lambda self, object_type, object_id, account_id, action, action_record_id=None: resolve_tenant_of(AdAccount, account_id))
def update_delivery_object_task(self, object_type: str, object_id: str, account_id: str, action: str, action_record_id: str | None = None) -> Dict:
    """异步暂停/启用单个 AdSet 或 Ad。"""
    db = SessionLocal()
    try:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            return {"status": "failed", "error": "广告账户不存在"}
        ref = CredentialResolver(db).for_account(account.id)
        remote_status = "PAUSED" if action in {"PAUSE", "ARCHIVE", "DELETE", "RESTORE"} else "ACTIVE"
        desired_status = (
            "DELETED" if action == "DELETE"
            else "ARCHIVED" if action == "ARCHIVE"
            else remote_status
        )
        action_row = db.query(DeliveryAction).filter(DeliveryAction.id == action_record_id).first() if action_record_id else None
        if action_row:
            action_row.status = "RUNNING"
            action_row.started_at = datetime.utcnow()
            db.commit()
        if object_type == "ADSET":
            obj = db.query(AdSetInstance).filter(AdSetInstance.id == object_id).first()
            if not obj or not obj.meta_adset_id:
                raise RuntimeError("广告组 Meta ID 不存在")
            FBConnectorClient().update_object(
                "ADSET",
                obj.meta_adset_id,
                ref.credential_id,
                {"status": remote_status},
                idempotency_key=f"{action}:adset:{obj.meta_adset_id}",
            )
            obj.meta_status = remote_status
            obj.status = desired_status
            obj.desired_status = desired_status
            now = datetime.utcnow()
            obj.archived_at = now if action == "ARCHIVE" else None
            obj.deleted_at = now if action == "DELETE" else None
            obj.last_action_id = action_record_id
            obj.last_synced_at = datetime.utcnow()
        elif object_type == "AD":
            obj = db.query(AdInstance).filter(AdInstance.id == object_id).first()
            if not obj or not obj.meta_ad_id:
                raise RuntimeError("广告 Meta ID 不存在")
            FBConnectorClient().update_object(
                "AD",
                obj.meta_ad_id,
                ref.credential_id,
                {"status": remote_status},
                idempotency_key=f"{action}:ad:{obj.meta_ad_id}",
            )
            obj.meta_status = remote_status
            obj.status = desired_status
            obj.desired_status = desired_status
            now = datetime.utcnow()
            obj.archived_at = now if action == "ARCHIVE" else None
            obj.deleted_at = now if action == "DELETE" else None
            obj.last_action_id = action_record_id
            obj.last_synced_at = datetime.utcnow()
        else:
            raise RuntimeError("不支持的投放对象类型")
        if action_row:
            action_row.status = "SUCCESS"
            action_row.remote_status = remote_status
            action_row.result_payload = {"state": desired_status}
            action_row.finished_at = datetime.utcnow()
        db.commit()
        return {"status": "success", "object_type": object_type, "object_id": object_id, "state": remote_status}
    except Exception as exc:
        db.rollback()
        if action_record_id:
            action_row = db.query(DeliveryAction).filter(DeliveryAction.id == action_record_id).first()
            if action_row:
                action_row.status = "FAILED"
                action_row.error_message = str(exc)[:1000]
                action_row.finished_at = datetime.utcnow()
                db.commit()
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
