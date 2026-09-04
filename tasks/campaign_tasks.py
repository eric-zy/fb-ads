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
from models import CampaignInstance, CampaignJob, CampaignJobItem
from services.campaign_builder import CampaignDeploymentBuilder
from services.credential_service import CredentialError, CredentialService
from services.meta import MetaApiError

# 未到达终态的子项状态
_ACTIVE_ITEM_STATUSES = [JobItemStatus.PENDING.value, JobItemStatus.RUNNING.value]


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
    # Token 失效/权限不足时标记凭据，避免后续任务重复做无效调用
    if category in (ErrorCategory.AUTH, ErrorCategory.PERMISSION):
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

        params = job.params or {}
        budget_override = params.get("budget_override")
        # 默认 PAUSED：批量创建后不直接花钱，由用户确认后再启用
        status = params.get("status", InstanceStatus.PAUSED.value)

        # 每个账户解析自己的 token（多 BM / 多账户架构的关键）
        try:
            service = CredentialService(db).build_service(item.ad_account_id)
        except CredentialError as e:
            item.mark_failed("NO_CREDENTIAL", str(e), ErrorCategory.AUTH)
            db.commit()
            logger.error(f"[JobItem {job_item_id}] 凭据不可用: {e}")
            return {"error": str(e)}

        builder = CampaignDeploymentBuilder(
            db,
            service,
            template,
            ad_account_id=item.ad_account_id,
            meta_ad_account_id=account.account_id,
            budget_override=budget_override,
            status=status,
        )
        result = builder.build()

        item.status = JobItemStatus.SUCCESS.value
        item.campaign_instance_id = result.get("campaign_instance_id")
        item.meta_campaign_id = result.get("meta_campaign_id")
        item.adset_ids = result.get("adset_ids")
        item.ad_ids = result.get("ad_ids")
        item.response_payload = result
        db.commit()

        logger.info(
            f"[JobItem {job_item_id}] 部署成功 campaign={result.get('meta_campaign_id')}"
        )
        return result

    except MetaApiError as e:
        db.rollback()
        logger.error(f"[JobItem {job_item_id}] Meta 调用失败: {e}")
        _mark_item_failed(db, job_item_id, e.code, e.message, e.category)
        return {"error": e.message, "category": e.category.value}
    except Exception as e:  # 兜底，避免 worker 静默吞异常
        db.rollback()
        logger.exception(f"[JobItem {job_item_id}] 未预期异常")
        _mark_item_failed(db, job_item_id, None, str(e), ErrorCategory.UNKNOWN)
        return {"error": str(e)}
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

        service = CredentialService(db).build_service(item.ad_account_id)

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
