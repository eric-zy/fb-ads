"""批量投放 Celery 任务（设计文档第 39 节 / 原则二：任务异步）

不要让 HTTP 请求等待几十、几百甚至几千个广告账户完成。

    HTTP Request → Create Job → Return job_id → Worker Async Execute

每个账户一个子任务，独立成状态（原则三）；失败只影响自己（第 30 节）；
幂等由 campaign_instances 的唯一约束保证，Retry ≠ Duplicate（原则四）。
"""
from datetime import datetime
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.enums import (
    ActionType,
    ErrorCategory,
    InstanceStatus,
    JobItemStatus,
    JobStatus,
)
from core.logger import logger
from core.tenant import resolve_tenant_of, tenant_task
from models import CampaignInstance, AdSetInstance, AdInstance, CampaignInstance, CampaignJob, CampaignJobItem, CreativeAsset, MetaAssetBinding, AdAccount, MetaPage, SinanCredential
from services.campaign_builder import CampaignDeploymentBuilder
from services.credential_service import CredentialError, CredentialService
from services.credential_resolver import CredentialResolver
from services.connector_campaign_builder import build_connector_payload
from services.fb_connector_client import FBConnectorClient
from services.meta import MetaApiError
from services.meta.page_access import page_account_access_error
from services.integrations.sinan_client import SinanClient
from core.security import decrypt_token
from tasks.meta_sync_tasks import sync_delivery_objects_task
import copy
import os

# 未到达终态的子项状态
_ACTIVE_ITEM_STATUSES = [JobItemStatus.PENDING.value, JobItemStatus.RUNNING.value]

@shared_task(bind=True, name="campaign.poll_connector_deployment", max_retries=20, default_retry_delay=15)
@tenant_task(lambda self, job_item_id: resolve_tenant_of(CampaignJobItem, job_item_id))
def poll_connector_deployment_task(self, job_item_id: str) -> Dict[str, Any]:
    """轮询海外部署结果，并将最终 Meta ID 回写国内任务项。"""
    db = SessionLocal()
    try:
        item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
        if not item:
            return {"status": "failed", "error": "任务项不存在"}
        if item.status == JobItemStatus.SUCCESS.value:
            return {"status": "success", "job_item_id": job_item_id, "meta_campaign_id": item.meta_campaign_id, "skipped": True}
        connector = (item.response_payload or {}).get("connector") or {}
        remote_id = connector.get("connector_task_id")
        if not remote_id:
            raise RuntimeError("缺少海外任务 ID")
        result = FBConnectorClient().deploy_status(remote_id)
        status = result.get("status")
        item.response_payload = {**(item.response_payload or {}), "connector_status": result}
        if status in {"QUEUED", "RUNNING", "CAMPAIGN_CREATED", "ADSETS_CREATED", "CREATIVES_CREATED"}:
            db.commit()
            raise self.retry()
        if status == "FAILED":
            cleanup = None
            try:
                credential_id = ((item.response_payload or {}).get("protocol") or {}).get("credential_id")
                if credential_id:
                    cleanup = FBConnectorClient().cleanup_deployment(remote_id, credential_id)
            except Exception as exc:
                cleanup = {"status": "FAILED", "error": str(exc)}
            item.mark_failed(result.get("error_code") or "CONNECTOR_DEPLOY_FAILED", result.get("error_message") or "海外投放创建失败", ErrorCategory.UNKNOWN)
            item.response_payload = {**(item.response_payload or {}), "cleanup": cleanup}
            db.commit()
            _finalize_job_if_done(db, item.job_id)
            db.commit()
            return {"status": "failed", "job_item_id": job_item_id}
        item.status = JobItemStatus.SUCCESS.value
        item.meta_campaign_id = result.get("campaign_id")
        objects = result.get("objects") or {}
        item.adset_ids = [x.get("id") for x in objects.get("adsets", []) if x.get("id")]
        item.ad_ids = [x.get("id") for x in objects.get("ads", []) if x.get("id")]
        template_id = item.job.template_id
        instance = db.query(CampaignInstance).filter(CampaignInstance.template_id == template_id, CampaignInstance.ad_account_id == item.ad_account_id).first()
        if not instance:
            instance = CampaignInstance(id=uuid.uuid4().hex, template_id=template_id, ad_account_id=item.ad_account_id, meta_campaign_id=item.meta_campaign_id, status="PAUSED")
            db.add(instance)
        else:
            instance.meta_campaign_id = item.meta_campaign_id
        item.campaign_instance_id = instance.id
        adsets_by_key = {}
        for pos, remote in enumerate(objects.get("adsets", []), 1):
            row = AdSetInstance(id=uuid.uuid4().hex, campaign_instance_id=instance.id, meta_adset_id=remote.get("id"), name=remote.get("client_key") or f"AdSet {pos}", status="PAUSED")
            db.add(row); adsets_by_key[remote.get("client_key")] = row
        for pos, remote in enumerate(objects.get("ads", []), 1):
            # 当前协议返回的 Ad client_key 为 ad-{adset}-{creative}，按顺序兜底挂到对应 AdSet。
            adset = list(adsets_by_key.values())[min(pos - 1, len(adsets_by_key) - 1)] if adsets_by_key else None
            if adset:
                db.add(AdInstance(id=uuid.uuid4().hex, adset_instance_id=adset.id, meta_ad_id=remote.get("id"), name=remote.get("client_key") or f"Ad {pos}", status="PAUSED"))
        db.commit()
        _finalize_job_if_done(db, item.job_id)
        db.commit()
        return {"status": "success", "job_item_id": job_item_id, "meta_campaign_id": item.meta_campaign_id}
    finally:
        db.close()


@shared_task(bind=True, name="meta.retry_asset_binding", max_retries=2, default_retry_delay=30)
@tenant_task(lambda self, binding_id: resolve_tenant_of(MetaAssetBinding, binding_id))
def retry_asset_binding_task(self, binding_id: str) -> Dict[str, Any]:
    """独立重试单个素材到账户的 Meta 上传。"""
    db = SessionLocal()
    try:
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        if not binding:
            return {"status": "failed", "error": "素材映射不存在"}
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == binding.asset_id).first()
        account = db.query(AdAccount).filter(AdAccount.id == binding.ad_account_id).first()
        if not asset or not asset.file_path or not os.path.exists(asset.file_path):
            raise RuntimeError("素材文件不存在")
        if not account:
            raise RuntimeError("广告账户不存在")
        service = CredentialService(db).build_service(account.id)
        binding.status = "UPLOADING"
        binding.error_message = None
        db.commit()
        result = (service.upload_video(account.account_id, asset.file_path)
                  if asset.asset_type == "video"
                  else service.upload_image(account.account_id, asset.file_path))
        binding.meta_asset_id = result.get("video_id") if asset.asset_type == "video" else result.get("hash")
        if not binding.meta_asset_id:
            raise RuntimeError("Meta 未返回素材 ID")
        binding.status = "READY"
        binding.uploaded_at = datetime.utcnow()
        binding.last_verified_at = datetime.utcnow()
        db.commit()
        return {"status": "success", "binding": binding.to_dict()}
    except Exception as exc:
        db.rollback()
        binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding_id).first()
        if binding:
            binding.status = "FAILED"
            binding.error_message = str(exc)
            if isinstance(exc, MetaApiError):
                binding.error_code = f"META_{exc.category.value}"
            db.commit()
        # 权限/对象不存在/校验错误需要重新授权或修正资产，不应自动重复上传。
        if isinstance(exc, MetaApiError) and not exc.retryable:
            return {"status": "failed", "binding_id": binding_id, "error": str(exc)}
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


def _prepare_template_assets(db: Session, service: Any, template: Any, ad_account_id: str, meta_ad_account_id: str) -> Any:
    """在账户子任务内按需上传素材，并解析为当前账户专属的 Meta ID。"""
    config = copy.deepcopy(template.creative_config_json or {})
    # 兼容新模板的公共文案配置，以及旧模板的创意级配置。
    # 仅在本次账户部署副本中合并，不回写公共模板，避免不同账户之间互相污染。
    shared = config.get("shared_creative") or {}
    if not isinstance(shared, dict):
        shared = {}
    creatives = config.get("creatives")
    if not isinstance(creatives, list):
        creatives = [config] if config else []
    for creative in creatives:
        if isinstance(creative, dict):
            for field in ("primary_text", "headline", "description", "cta", "landing_url"):
                if (creative.get(field) is None or creative.get(field) == "") and shared.get(field) not in (None, ""):
                    creative[field] = shared[field]
    carousel_cards = config.get("carousel_cards")
    if isinstance(carousel_cards, list):
        for card in carousel_cards:
            if isinstance(card, dict):
                for field in ("primary_text", "headline", "description", "cta", "landing_url"):
                    if (card.get(field) is None or card.get(field) == "") and shared.get(field) not in (None, ""):
                        card[field] = shared[field]
    # 直接投放时创意可能挂在 adsets[].creatives，而不是顶层 creatives。
    # 两种结构都要注入当前广告账户对应的 image_hash/video_id。
    creative_groups = [creatives]
    creative_groups.extend(
        adset.get("creatives")
        for adset in (config.get("adsets") or [])
        if isinstance(adset, dict) and isinstance(adset.get("creatives"), list)
    )
    for creative in (item for group in creative_groups for item in group):
        if not isinstance(creative, dict):
            continue
        asset_id = creative.get("asset_id")
        if not asset_id:
            continue
        asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first()
        if not asset or not asset.file_path or not os.path.exists(asset.file_path):
            raise RuntimeError(f"素材文件不存在: {asset_id}")
        binding = db.query(MetaAssetBinding).filter(
            MetaAssetBinding.asset_id == asset_id,
            MetaAssetBinding.ad_account_id == ad_account_id,
        ).first()
        if not binding:
            import uuid
            binding = MetaAssetBinding(id=uuid.uuid4().hex, tenant_id=account.tenant_id, asset_id=asset_id,
                                       ad_account_id=ad_account_id,
                                       meta_asset_type=asset.asset_type, status="PENDING")
            db.add(binding)
            db.flush()
        if binding.status != "READY" or not binding.meta_asset_id:
            binding.status = "UPLOADING"
            binding.error_message = None
            db.commit()
            try:
                result = (service.upload_video(meta_ad_account_id, asset.file_path)
                          if asset.asset_type == "video"
                          else service.upload_image(meta_ad_account_id, asset.file_path))
                meta_id = result.get("video_id") if asset.asset_type == "video" else result.get("hash")
                if not meta_id:
                    raise RuntimeError("Meta 未返回素材 ID")
                binding.meta_asset_id = meta_id
                binding.status = "READY"
                binding.uploaded_at = datetime.utcnow()
                binding.last_verified_at = datetime.utcnow()
                db.commit()
            except Exception as exc:
                db.rollback()
                binding = db.query(MetaAssetBinding).filter(MetaAssetBinding.id == binding.id).first()
                if binding:
                    binding.status = "FAILED"
                    binding.error_message = str(exc)
                    db.commit()
                raise
        meta_id = binding.meta_asset_id
        creative["video_id" if asset.asset_type == "video" else "image_hash"] = meta_id
    if config.get("creative_format") == "CAROUSEL":
        for index, card in enumerate(config.get("carousel_cards") or [], 1):
            asset_id = card.get("asset_id")
            asset = db.query(CreativeAsset).filter(CreativeAsset.id == asset_id).first() if asset_id else None
            if not asset or asset.asset_type != "image":
                raise RuntimeError(f"轮播第 {index} 张卡片图片素材不存在或类型错误")
            binding = db.query(MetaAssetBinding).filter(
                MetaAssetBinding.asset_id == asset_id,
                MetaAssetBinding.ad_account_id == ad_account_id,
            ).first()
            if not binding or binding.status != "READY" or not binding.meta_asset_id:
                raise RuntimeError(f"轮播第 {index} 张卡片素材尚未同步完成")
            card["image_hash"] = binding.meta_asset_id
            card["asset_type"] = "image"
    config["creatives"] = creatives
    return config


# ----------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------
def _finalize_job_if_done(db: Session, job_id: Optional[str]) -> None:
    """所有子项到达终态后汇总 Job 状态（设计文档第 30 节：部分成功）

    100 个账户成功 93 个 → PARTIAL_SUCCESS，而不是把整个 Job 标记失败。
    """
    if not job_id:
        return

    job = db.query(CampaignJob).filter(CampaignJob.id == job_id).first()
    if not job:
        return

    pending = (
        db.query(CampaignJobItem)
        .filter(
            CampaignJobItem.job_id == job_id,
            CampaignJobItem.status.in_(_ACTIVE_ITEM_STATUSES),
        )
        .count()
    )
    if pending > 0:
        return  # 仍有子项在执行

    success = (
        db.query(CampaignJobItem)
        .filter(
            CampaignJobItem.job_id == job_id,
            CampaignJobItem.status == JobItemStatus.SUCCESS.value,
        )
        .count()
    )
    failed = (
        db.query(CampaignJobItem)
        .filter(
            CampaignJobItem.job_id == job_id,
            CampaignJobItem.status == JobItemStatus.FAILED.value,
        )
        .count()
    )

    job.success_count = success
    job.failed_count = failed
    job.finished_at = datetime.utcnow()

    if failed == 0:
        job.status = JobStatus.SUCCESS.value
    elif success == 0:
        job.status = JobStatus.FAILED.value
    else:
        job.status = JobStatus.PARTIAL_SUCCESS.value

    db.commit()
    logger.info(f"[Job {job_id}] 完成 status={job.status} success={success} failed={failed}")


def _mark_item_failed(
    db: Session,
    job_item_id: str,
    code: Optional[Any],
    message: str,
    category: ErrorCategory,
) -> None:
    """标记子项失败；认证/权限类错误同时标记凭据异常"""
    item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
    if not item:
        return

    item.mark_failed(
        code=str(code) if code is not None else None,
        message=message,
        category=category,
    )
    # 保留结构化失败摘要，供任务页展示；不写入 access token 或完整请求体。
    payload = item.response_payload if isinstance(item.response_payload, dict) else {}
    payload.update({
        "failure": {
            "category": category.value if isinstance(category, ErrorCategory) else str(category),
            "code": str(code) if code is not None else None,
            "message": message,
        }
    })
    item.response_payload = payload
    # 只有 Token 本身失效才禁用凭据。对象级权限不足不代表该 Token 对
    # 其它 BM/账户也无效，不能因此切断整条 OAuth 授权连接。
    if category == ErrorCategory.AUTH:
        CredentialService(db).mark_invalid_by_account(item.ad_account_id, message)
    db.commit()


# ----------------------------------------------------------------------
# Job 编排
# ----------------------------------------------------------------------
@shared_task(bind=True, name="campaign.execute_job")
@tenant_task(lambda self, job_id: resolve_tenant_of(CampaignJob, job_id))
def execute_campaign_job(self, job_id: str) -> Dict[str, Any]:
    """Job 编排：把子项分派到队列，不在此处循环调用 Meta API

    （设计文档第 16 节：不建议直接循环调用 API）
    """
    db = SessionLocal()
    try:
        job = db.query(CampaignJob).filter(CampaignJob.id == job_id).first()
        if not job:
            logger.error(f"[Job {job_id}] 不存在")
            return {"error": "job not found"}

        if job.status == JobStatus.CANCELLED.value:
            logger.info(f"[Job {job_id}] 已取消，跳过执行")
            return {"job_id": job_id, "dispatched": 0, "cancelled": True}

        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        db.commit()

        items = (
            db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.job_id == job_id,
                CampaignJobItem.status.in_(
                    [JobItemStatus.PENDING.value, JobItemStatus.FAILED.value]
                ),
            )
            .all()
        )

        # 重跑失败项：重置为 PENDING 并累计重试次数
        for item in items:
            if item.status == JobItemStatus.FAILED.value:
                item.status = JobItemStatus.PENDING.value
                item.retry_count = (item.retry_count or 0) + 1
                item.error_code = None
                item.error_message = None
                item.error_category = None
        db.commit()

        is_create = job.action_type == ActionType.CREATE.value
        for item in items:
            if is_create:
                create_campaign_for_account.delay(item.id)
            else:
                apply_action_for_account.delay(item.id)

        logger.info(
            f"[Job {job_id}] action={job.action_type} 已分派 {len(items)} 个子任务"
        )
        return {"job_id": job_id, "dispatched": len(items)}
    finally:
        db.close()


# ----------------------------------------------------------------------
# CREATE：把模板部署到单个账户
# ----------------------------------------------------------------------
@shared_task(bind=True, name="campaign.create_for_account")
@tenant_task(lambda self, job_item_id: resolve_tenant_of(CampaignJobItem, job_item_id))
def create_campaign_for_account(self, job_item_id: str) -> Dict[str, Any]:
    """单个账户的部署执行（设计文档第 39 节）"""
    db = SessionLocal()
    job_id: Optional[str] = None
    try:
        item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
        if not item:
            return {"error": "job item not found"}

        job_id = item.job_id
        # 幂等：已成功则直接跳过（原则四：Retry ≠ Duplicate）
        if item.status == JobItemStatus.SUCCESS.value:
            return {"skipped": True, "reason": "already success"}

        item.status = JobItemStatus.RUNNING.value
        db.commit()

        job = item.job
        template = job.template
        account = item.ad_account

        if not template:
            item.mark_failed("NO_TEMPLATE", "Job 未关联投放模板", ErrorCategory.VALIDATION)
            db.commit()
            return {"error": "template missing"}
        if not account:
            item.mark_failed("NO_ACCOUNT", "广告账户不存在", ErrorCategory.VALIDATION)
            db.commit()
            return {"error": "account missing"}

        page_id = (template.creative_config_json or {}).get("page_id")
        page = db.query(MetaPage).filter(
            MetaPage.page_id == str(page_id or ""),
            MetaPage.status == "ACTIVE",
        ).first()
        if not page:
            item.mark_failed(
                "PAGE_UNAVAILABLE",
                "Facebook 页面未授权、已失效或不属于当前租户",
                ErrorCategory.AUTH,
            )
            db.commit()
            return {"error": "facebook page unavailable"}

        page_error = page_account_access_error(page, account)
        if page_error:
            item.mark_failed("PAGE_ACCOUNT_MISMATCH", page_error, ErrorCategory.AUTH)
            db.commit()
            return {"error": page_error}

        params = job.params or {}
        budget_override = params.get("budget_override")
        # 默认 PAUSED：批量创建后不直接花钱，由用户确认后再启用
        status = params.get("status", InstanceStatus.PAUSED.value)
        sinan = {}
        sinan_promotion_id = params.get("sinan_promotion_id")
        if sinan_promotion_id:
            sinan_credential = db.query(SinanCredential).first()
            if not sinan_credential or sinan_credential.status != "ACTIVE":
                raise ValueError("司南账号未验证，无法读取推广链")
            sinan = SinanClient(
                sinan_credential.base_url,
                sinan_credential.app_id,
                decrypt_token(sinan_credential.access_token_encrypted),
                decrypt_token(sinan_credential.refresh_token_encrypted),
                sinan_credential.menu_id,
            ).promotion_detail_sync(sinan_promotion_id)
            if str(sinan.get("status")).upper() in {"0", "DISABLED", "INACTIVE", "ARCHIVED"}:
                raise ValueError("司南推广链已停用或不可投放")
            if not sinan.get("landing_url"):
                raise ValueError("司南推广链未返回有效推广链接")

        # Connector 模式只在国内生成协议并投递海外任务，国内不读取 FB Token。
        ref = CredentialResolver(db).for_account(item.ad_account_id)
        if ref.mode == "connector":
            protocol_payload = build_connector_payload(
                template, account.account_id, budget_override=budget_override,
                status=status, campaign_name=sinan.get("campaign_name"),
                adset_name=sinan.get("adset_name"),
            )
            protocol_payload.update({
                "task_id": job_item_id,
                "credential_id": ref.credential_id,
                "account_id": account.account_id,
                "idempotency_key": f"deploy:{job_item_id}:v1",
            })
            result = FBConnectorClient().deploy_campaign(protocol_payload, idempotency_key=protocol_payload["idempotency_key"])
            item.status = JobItemStatus.RUNNING.value
            item.response_payload = {"connector": result, "protocol": protocol_payload}
            db.commit()
            poll_connector_deployment_task.apply_async(args=[job_item_id], countdown=5)
            return {"status": "QUEUED", "job_item_id": job_item_id, **result}

        # direct 模式每个账户解析自己的 token（多 BM / 多账户架构的关键）
        try:
            service = CredentialService(db).build_service(
                item.ad_account_id,
                access_business_id=item.access_business_id,
            )
        except CredentialError as e:
            item.mark_failed("NO_CREDENTIAL", str(e), ErrorCategory.AUTH)
            db.commit()
            logger.error(f"[JobItem {job_item_id}] 凭据不可用: {e}")
            return {"error": str(e)}

        original_creative_config = template.creative_config_json
        original_template_name = template.name
        if sinan.get("landing_url"):
            patched_config = copy.deepcopy(template.creative_config_json or {})
            creatives = patched_config.get("creatives") if isinstance(patched_config.get("creatives"), list) else [patched_config]
            for creative in creatives: creative["landing_url"] = sinan["landing_url"]
            patched_config["creatives"] = creatives
            if isinstance(patched_config.get("carousel_cards"), list):
                for card in patched_config["carousel_cards"]:
                    if isinstance(card, dict): card["landing_url"] = sinan["landing_url"]
            template.creative_config_json = patched_config
        template.creative_config_json = _prepare_template_assets(
            db, service, template, item.ad_account_id, account.account_id
        )

        try:
            builder = CampaignDeploymentBuilder(
                db,
                service,
                template,
                ad_account_id=item.ad_account_id,
                meta_ad_account_id=account.account_id,
                budget_override=budget_override,
                status=status,
                campaign_name=sinan.get("campaign_name"),
                adset_name=sinan.get("adset_name"),
            )
            result = builder.build()
        finally:
            # 账户专属 hash/video_id 只应进入映射表，不能污染公共模板。
            template.creative_config_json = original_creative_config
            template.name = original_template_name

        item.status = JobItemStatus.SUCCESS.value
        item.campaign_instance_id = result.get("campaign_instance_id")
        item.meta_campaign_id = result.get("meta_campaign_id")
        item.adset_ids = result.get("adset_ids")
        item.ad_ids = result.get("ad_ids")
        item.response_payload = result
        db.commit()

        # 发布完成后自动拉取一次 Meta 状态，详情页无需等待人工点击“同步 Meta”。
        # 同步失败不影响已成功的发布结果，由同步任务自身记录并可在页面手动重试。
        sync_delivery_objects_task.delay(item.ad_account_id)

        logger.info(
            f"[JobItem {job_item_id}] 部署成功 campaign={result.get('meta_campaign_id')}"
        )
        return result

    except MetaApiError as e:
        db.rollback()
        logger.error(f"[JobItem {job_item_id}] Meta 调用失败: {e}")
        cleanup_attempted = getattr(e, "cleanup_attempted_ids", [])
        cleanup = getattr(e, "cleanup_failed_ids", [])
        if cleanup:
            item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
            if item:
                item.response_payload = {
                    "cleanup_attempted": True,
                    "cleanup_attempted_object_ids": cleanup_attempted,
                    "cleanup_failed": True,
                    "cleanup_object_ids": cleanup,
                }
        message = e.message
        if cleanup:
            message += f"；补偿清理失败对象: {', '.join(cleanup)}"
        _mark_item_failed(db, job_item_id, e.code, message, e.category)
        return {"error": message, "category": e.category.value}
    except ValueError as e:
        # 模板参数在调用 Meta 前校验，按业务校验失败记录，避免被归类为 UNKNOWN。
        db.rollback()
        logger.error(f"[JobItem {job_item_id}] 投放参数校验失败: {e}")
        cleanup_attempted = getattr(e, "cleanup_attempted_ids", [])
        cleanup = getattr(e, "cleanup_failed_ids", [])
        if cleanup_attempted or cleanup:
            item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
            if item:
                item.response_payload = {
                    "cleanup_attempted": True,
                    "cleanup_attempted_object_ids": cleanup_attempted,
                    "cleanup_failed": bool(cleanup),
                    "cleanup_object_ids": cleanup,
                }
        message = str(e) + (f"；补偿清理失败对象: {', '.join(cleanup)}" if cleanup else "")
        _mark_item_failed(db, job_item_id, "INVALID_TEMPLATE", message, ErrorCategory.VALIDATION)
        return {"error": message, "category": ErrorCategory.VALIDATION.value}
    except Exception as e:  # 兜底，避免 worker 静默吞异常
        db.rollback()
        logger.exception(f"[JobItem {job_item_id}] 未预期异常")
        cleanup_attempted = getattr(e, "cleanup_attempted_ids", [])
        cleanup = getattr(e, "cleanup_failed_ids", [])
        if cleanup_attempted or cleanup:
            item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
            if item:
                item.response_payload = {
                    "cleanup_attempted": True,
                    "cleanup_attempted_object_ids": cleanup_attempted,
                    "cleanup_failed": bool(cleanup),
                    "cleanup_object_ids": cleanup,
                }
        message = str(e) + (f"；补偿清理失败对象: {', '.join(cleanup)}" if cleanup else "")
        _mark_item_failed(db, job_item_id, None, message, ErrorCategory.UNKNOWN)
        return {"error": message}
    finally:
        _finalize_job_if_done(db, job_id)
        db.close()


# ----------------------------------------------------------------------
# 批量启停 / 批量改预算（设计文档第 22 / 23 节）
# ----------------------------------------------------------------------
@shared_task(bind=True, name="campaign.apply_action_for_account")
@tenant_task(lambda self, job_item_id: resolve_tenant_of(CampaignJobItem, job_item_id))
def apply_action_for_account(self, job_item_id: str) -> Dict[str, Any]:
    """对已部署实例执行 PAUSE / ENABLE / UPDATE_BUDGET

    通过 campaign_instances（模板 × 账户映射）找到 Meta Campaign ID，
    再调用 Meta API —— 这正是"实例映射"表的价值所在。
    """
    db = SessionLocal()
    job_id: Optional[str] = None
    try:
        item = db.query(CampaignJobItem).filter(CampaignJobItem.id == job_item_id).first()
        if not item:
            return {"error": "job item not found"}

        job_id = item.job_id
        if item.status == JobItemStatus.SUCCESS.value:
            return {"skipped": True, "reason": "already success"}

        item.status = JobItemStatus.RUNNING.value
        db.commit()

        job = item.job
        action = job.action_type
        params = job.params or {}

        service = CredentialService(db).build_service(
            item.ad_account_id,
            access_business_id=item.access_business_id,
        )

        # 优先用子项记录的实例，其次按 模板+账户 反查
        instance = item.campaign_instance
        if not instance and job.template_id:
            instance = (
                db.query(CampaignInstance)
                .filter(
                    CampaignInstance.template_id == job.template_id,
                    CampaignInstance.ad_account_id == item.ad_account_id,
                )
                .first()
            )
        if not instance:
            item.mark_failed(
                "NO_INSTANCE", "该账户下未找到已部署的 Campaign 实例", ErrorCategory.VALIDATION
            )
            db.commit()
            return {"error": "no instance"}

        if action == ActionType.PAUSE.value:
            service.pause_campaign(instance.meta_campaign_id)
            instance.status = InstanceStatus.PAUSED.value
            instance.meta_status = InstanceStatus.PAUSED.value
        elif action == ActionType.ENABLE.value:
            service.enable_campaign(instance.meta_campaign_id)
            instance.status = InstanceStatus.ACTIVE.value
            instance.meta_status = InstanceStatus.ACTIVE.value
        elif action == ActionType.UPDATE_BUDGET.value:
            budget = params.get("budget_override")
            if not budget:
                item.mark_failed(
                    "NO_BUDGET", "未提供 budget_override", ErrorCategory.VALIDATION
                )
                db.commit()
                return {"error": "budget required"}
            # 预算在 AdSet 维度（设计文档第 22 节：找到实例 → 改预算）
            for adset in instance.adsets:
                service.update_budget(adset.meta_adset_id, budget, level="adset")
        else:
            item.mark_failed(
                "UNSUPPORTED_ACTION", f"不支持的动作: {action}", ErrorCategory.VALIDATION
            )
            db.commit()
            return {"error": f"unsupported action: {action}"}

        item.status = JobItemStatus.SUCCESS.value
        item.meta_campaign_id = instance.meta_campaign_id
        db.commit()
        return {"ok": True, "action": action, "campaign_id": instance.meta_campaign_id}

    except MetaApiError as e:
        db.rollback()
        logger.error(f"[JobItem {job_item_id}] 批量操作失败: {e}")
        _mark_item_failed(db, job_item_id, e.code, e.message, e.category)
        return {"error": e.message, "category": e.category.value}
    except Exception as e:
        db.rollback()
        logger.exception(f"[JobItem {job_item_id}] 未预期异常")
        _mark_item_failed(db, job_item_id, None, str(e), ErrorCategory.UNKNOWN)
        return {"error": str(e)}
    finally:
        _finalize_job_if_done(db, job_id)
        db.close()


# ----------------------------------------------------------------------
# 重跑失败项（设计文档第 30 节）
# ----------------------------------------------------------------------
@shared_task(bind=True, name="campaign.retry_failed_items")
@tenant_task(lambda self, job_id: resolve_tenant_of(CampaignJob, job_id))
def retry_failed_job_items(self, job_id: str) -> Dict[str, Any]:
    """只重跑失败的子项，而不是重新执行全部账户

    100 个账户失败 7 个 → 只重跑这 7 个。
    """
    db = SessionLocal()
    try:
        job = db.query(CampaignJob).filter(CampaignJob.id == job_id).first()
        if not job:
            return {"error": "job not found"}

        failed_items = (
            db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.job_id == job_id,
                CampaignJobItem.status == JobItemStatus.FAILED.value,
            )
            .all()
        )
        for item in failed_items:
            item.status = JobItemStatus.PENDING.value
            item.retry_count = (item.retry_count or 0) + 1
            item.error_code = None
            item.error_message = None
            item.error_category = None
        db.commit()

        job.status = JobStatus.RUNNING.value
        db.commit()

        is_create = job.action_type == ActionType.CREATE.value
        for item in failed_items:
            if is_create:
                create_campaign_for_account.delay(item.id)
            else:
                apply_action_for_account.delay(item.id)

        logger.info(f"[Job {job_id}] 重跑 {len(failed_items)} 个失败子项")
        return {"job_id": job_id, "retried": len(failed_items)}
    finally:
        db.close()
