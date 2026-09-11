"""Job Service —— 批量任务创建与管理（设计文档第 17 / 29 节）

原则二：任务异步
    HTTP Request → Create Job → Return job_id → Worker Async Execute

创建 Job 时不调用任何 Meta API，只写库并派发 Celery 子任务后立即返回，
前端随后轮询 GET /api/v1/jobs/{id} 查看进度。
"""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.enums import ActionType, InstanceStatus, JobItemStatus, JobStatus
from core.logger import logger
from models import (
    AdAccount,
    CampaignInstance,
    CampaignJob,
    CampaignJobItem,
    CampaignTemplate,
    MetaPage,
)
from services.meta.page_access import page_account_access_error
from tasks.campaign_tasks import (
    execute_campaign_job,
    retry_failed_job_items,
)


def _new_id() -> str:
    return uuid.uuid4().hex


def build_request_hash(
    template_id: Optional[str],
    ad_account_id: str,
    action: str,
    key_params: Optional[Dict[str, Any]] = None,
) -> str:
    """幂等键（设计文档第 29 节）

    同一模板 + 同一账户 + 同一动作 + 相同关键参数 → 相同 hash。
    用于识别"同一次操作"，避免超时重试导致重复创建。
    """
    payload = json.dumps(
        {
            "template_id": template_id,
            "ad_account_id": ad_account_id,
            "action": action,
            "params": key_params or {},
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class JobService:
    """批量任务服务"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 投放前置校验
    # ------------------------------------------------------------------
    def preflight_campaign(
        self, template_id: str, ad_account_ids: List[str], budget_override: Optional[float] = None,
        status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """返回可读的发布前检查结果；不创建 Job，不调用 Meta 写接口。"""
        from services.meta import AdAccountService

        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        template = self.db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
        if not template:
            return {"passed": False, "errors": [{"code": "TEMPLATE_NOT_FOUND", "message": "投放模板不存在"}], "warnings": [], "accounts": []}
        if template.status != "ACTIVE":
            errors.append({"code": "TEMPLATE_INACTIVE", "message": "投放模板不是 ACTIVE 状态"})
        if status not in (InstanceStatus.PAUSED.value, InstanceStatus.ACTIVE.value):
            errors.append({"code": "INVALID_STATUS", "message": "初始状态只能是 PAUSED 或 ACTIVE"})
        budget = budget_override if budget_override is not None else (template.daily_budget or 0)
        if budget <= 0:
            errors.append({"code": "INVALID_BUDGET", "message": "预算必须大于 0"})
        config = template.creative_config_json or {}
        page_id = str(config.get("page_id") or "")
        if not page_id:
            errors.append({"code": "PAGE_REQUIRED", "message": "模板未选择 Facebook Page"})
        elif not self.db.query(MetaPage).filter(MetaPage.page_id == page_id, MetaPage.status == "ACTIVE").first():
            errors.append({"code": "PAGE_UNAVAILABLE", "message": "Facebook Page 未同步、已失效或不属于当前租户"})
        creatives = config.get("creatives") if isinstance(config.get("creatives"), list) else [config]
        if not creatives or all(not (c.get("asset_id") or c.get("image_hash") or c.get("video_id")) for c in creatives):
            errors.append({"code": "CREATIVE_REQUIRED", "message": "模板至少需要一个有效素材"})

        ids = list(dict.fromkeys(ad_account_ids or []))
        available, rejected = AdAccountService(self.db).filter_available_ids(ids, user_id=created_by)
        page = self.db.query(MetaPage).filter(
            MetaPage.page_id == page_id, MetaPage.status == "ACTIVE"
        ).first() if page_id else None
        if page:
            compatible = []
            for account_pk in available:
                account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
                reason = page_account_access_error(page, account) if account else "账户不存在"
                if reason:
                    rejected.append({"account_id": account_pk, "reason": reason})
                else:
                    compatible.append(account_pk)
            available = compatible

        account_results = [{"account_id": x, "status": "READY"} for x in available]
        account_results += [{"account_id": x.get("account_id"), "status": "BLOCKED", "reason": x.get("reason")} for x in rejected]
        if rejected:
            warnings.append({"code": "ACCOUNTS_REJECTED", "message": f"{len(rejected)} 个账户不可投放，将被剔除", "items": rejected})
        if not available:
            errors.append({"code": "NO_AVAILABLE_ACCOUNT", "message": "没有可投放的广告账户"})
        existing = self.db.query(CampaignInstance).filter(
            CampaignInstance.template_id == template_id,
            CampaignInstance.ad_account_id.in_(available),
            CampaignInstance.status != InstanceStatus.DELETED.value,
        ).count() if available else 0
        if existing:
            warnings.append({"code": "ALREADY_DEPLOYED", "message": f"{existing} 个账户已有该模板实例，提交后会跳过创建"})
        return {"passed": not errors, "template": {"id": template.id, "name": template.name, "objective": template.objective, "creative_count": len(creatives)}, "errors": errors, "warnings": warnings, "accounts": account_results, "ready_account_ids": available}

    # 创建
    # ------------------------------------------------------------------
    @staticmethod
    def _key_params_for_hash(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """只有影响"操作语义"的参数才进入幂等键

        CREATE 不把预算等易变参数放进 hash：
        实例表 UNIQUE(template_id, ad_account_id) 已保证不会重复创建。
        """
        if action == ActionType.UPDATE_BUDGET.value:
            return {"budget": params.get("budget_override")}
        return {}

    def create_job(
        self,
        *,
        template_id: str,
        ad_account_ids: List[str],
        action_type: ActionType = ActionType.CREATE,
        params: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
        scheduled_at: Optional[datetime] = None,
    ) -> CampaignJob:
        """创建批量任务并派发到队列（立即返回，不阻塞 HTTP）

        Args:
            scheduled_at: 计划执行时间（UTC）。为空表示立即执行；
                传入未来时间则由 Celery 的 eta 机制延迟派发，
                Job 在此期间保持 QUEUED 状态（定时投放场景）。
        """
        template = (
            self.db.query(CampaignTemplate)
            .filter(CampaignTemplate.id == template_id)
            .first()
        )
        if not template:
            raise ValueError(f"投放模板不存在: {template_id}")
        if not ad_account_ids:
            raise ValueError("请至少选择一个广告账户")

        # XMP 式投放前置校验：模板引用的 Page 必须属于当前租户且仍有效。
        page_id = (template.creative_config_json or {}).get("page_id")
        if not page_id:
            raise ValueError("投放模板未选择 Facebook 页面，请先编辑模板选择已同步页面")
        page = self.db.query(MetaPage).filter(
            MetaPage.page_id == str(page_id),
            MetaPage.status == "ACTIVE",
        ).first()
        if not page:
            raise ValueError("模板引用的 Facebook 页面已失效或不属于当前租户，请重新同步并选择页面")

        # 文档 §19：可投放判断统一由后端 AdAccountService 完成，
        # 前端/调用方不得自行拼接规则。此处把不可投放的账户直接剔除，
        # 避免把已禁用、凭据失效或 Meta 侧异常的账户派发给 Meta。
        from services.meta import AdAccountService

        ad_account_ids, rejected = AdAccountService(self.db).filter_available_ids(ad_account_ids, user_id=created_by)
        compatible_ids = []
        for account_pk in ad_account_ids:
            account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
            reason = page_account_access_error(page, account) if account else "账户不存在"
            if reason:
                rejected.append({"account_id": account_pk, "reason": reason})
            else:
                compatible_ids.append(account_pk)
        ad_account_ids = compatible_ids
        if not ad_account_ids:
            detail = "；".join(f"{r['account_id']}: {r['reason']}" for r in rejected[:5])
            raise ValueError(f"所选账户均不可参与投放：{detail}")
        if rejected:
            logger.warning(
                f"[JobService] 剔除 {len(rejected)} 个不可投放账户: "
                + "；".join(f"{r['account_id']}({r['reason']})" for r in rejected[:5])
            )

        action_value = (
            action_type.value if isinstance(action_type, ActionType) else action_type
        )
        params = params or {}
        # 保留被前置校验剔除的账户，供前端明确提示，不进入投放子任务。
        if rejected:
            params = dict(params)
            params["rejected_accounts"] = rejected
        key_params = self._key_params_for_hash(action_value, params)

        # 仅在时间为「未来」时才按定时处理，过去的时间退化为立即执行
        is_scheduled = scheduled_at is not None and scheduled_at > datetime.utcnow()

        job = CampaignJob(
            id=_new_id(),
            template_id=template_id,
            action_type=action_value,
            status=JobStatus.QUEUED.value if is_scheduled else JobStatus.PENDING.value,
            total_accounts=len(ad_account_ids),
            params=params,
            created_by=created_by,
            scheduled_at=scheduled_at if is_scheduled else None,
        )
        self.db.add(job)
        self.db.flush()

        for account_id in ad_account_ids:
            self.db.add(
                CampaignJobItem(
                    id=_new_id(),
                    job_id=job.id,
                    ad_account_id=account_id,
                    status=JobItemStatus.PENDING.value,
                    request_hash=build_request_hash(
                        template_id, account_id, action_value, key_params
                    ),
                    request_payload={"template_id": template_id, "params": params},
                )
            )

        self.db.commit()
        self.db.refresh(job)

        # 异步派发：HTTP 请求到此结束，不等待 Meta API
        if is_scheduled:
            # 定时执行：由 Celery 的 eta 机制延迟投递，到点后才会真正执行
            async_result = execute_campaign_job.apply_async(args=[job.id], eta=scheduled_at)
            job.celery_task_id = async_result.id
            self.db.commit()
            logger.info(
                f"[JobService] 创建定时任务 {job.id} 计划执行于 {scheduled_at.isoformat()} "
                f"账户数={len(ad_account_ids)} celery_task={async_result.id}"
            )
        else:
            execute_campaign_job.delay(job.id)
            logger.info(
                f"[JobService] 创建任务 {job.id} action={action_value} "
                f"账户数={len(ad_account_ids)}"
            )
        return job

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_job(self, job_id: str) -> Optional[CampaignJob]:
        return self.db.query(CampaignJob).filter(CampaignJob.id == job_id).first()

    def list_jobs(self, limit: int = 50, status: Optional[str] = None) -> List[CampaignJob]:
        query = self.db.query(CampaignJob)
        if status:
            query = query.filter(CampaignJob.status == status)
        return query.order_by(CampaignJob.created_at.desc()).limit(limit).all()

    def list_scheduled_jobs(self, limit: int = 50) -> List[CampaignJob]:
        """待执行的定时任务（按计划执行时间升序）"""
        return (
            self.db.query(CampaignJob)
            .filter(
                CampaignJob.scheduled_at.isnot(None),
                CampaignJob.status.in_([JobStatus.PENDING.value, JobStatus.QUEUED.value]),
            )
            .order_by(CampaignJob.scheduled_at.asc())
            .limit(limit)
            .all()
        )

    def get_job_detail(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Job 详情 + 子项列表（供前端轮询进度）"""
        job = self.get_job(job_id)
        if not job:
            return None
        return {
            **job.to_dict(),
            "items": [item.to_dict() for item in job.items],
        }

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    @staticmethod
    def _revoke_celery_task(task_id: str) -> None:
        """撤销 Celery 中尚未执行的任务（失败不阻断本地状态更新）"""
        try:
            from celery_app import celery_app

            celery_app.control.revoke(task_id, terminate=False)
            logger.info(f"[JobService] 已撤销 Celery 任务 {task_id}")
        except Exception as e:
            logger.warning(f"[JobService] 撤销 Celery 任务 {task_id} 失败: {e}")

    def cancel_job(self, job_id: str) -> Optional[CampaignJob]:
        """取消任务：撤销未执行的 Celery 投递，未完成子项标记为 SKIPPED"""
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in (JobStatus.SUCCESS.value, JobStatus.FAILED.value):
            return job

        # 定时任务若尚未到执行时间，需撤销 Celery 中的 eta 投递
        if job.celery_task_id:
            self._revoke_celery_task(job.celery_task_id)

        job.status = JobStatus.CANCELLED.value
        self.db.query(CampaignJobItem).filter(
            CampaignJobItem.job_id == job_id,
            CampaignJobItem.status.in_(
                [JobItemStatus.PENDING.value, JobItemStatus.RUNNING.value]
            ),
        ).update(
            {CampaignJobItem.status: JobItemStatus.SKIPPED.value},
            synchronize_session=False,
        )
        self.db.commit()
        logger.info(f"[JobService] 任务 {job_id} 已取消")
        return job

    def retry_failed(self, job_id: str) -> int:
        """只重跑失败子项（设计文档第 30 节）"""
        job = self.get_job(job_id)
        if not job:
            return 0
        failed_count = (
            self.db.query(CampaignJobItem)
            .filter(
                CampaignJobItem.job_id == job_id,
                CampaignJobItem.status == JobItemStatus.FAILED.value,
            )
            .count()
        )
        if failed_count == 0:
            return 0
        retry_failed_job_items.delay(job_id)
        return failed_count

    def dispatch_now(self, job_id: str) -> Optional[CampaignJob]:
        """把定时任务提前为立即执行

        需先撤销原定的 eta 投递，否则到点后会重复执行一次。
        """
        job = self.get_job(job_id)
        if not job:
            return None
        if job.status in (
            JobStatus.SUCCESS.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ):
            return job

        if job.celery_task_id:
            self._revoke_celery_task(job.celery_task_id)
            job.celery_task_id = None

        job.scheduled_at = None
        job.status = JobStatus.PENDING.value
        self.db.commit()

        execute_campaign_job.delay(job.id)
        logger.info(f"[JobService] 定时任务 {job_id} 已提前执行")
        return job
