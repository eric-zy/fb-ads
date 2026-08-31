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

from core.enums import ActionType, JobItemStatus, JobStatus
from core.logger import logger
from models import CampaignJob, CampaignJobItem, CampaignTemplate
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

        # 文档 §19：可投放判断统一由后端 AdAccountService 完成，
        # 前端/调用方不得自行拼接规则。此处把不可投放的账户直接剔除，
        # 避免把已禁用、凭据失效或 Meta 侧异常的账户派发给 Meta。
        from services.meta import AdAccountService

        ad_account_ids, rejected = AdAccountService(self.db).filter_available_ids(ad_account_ids)
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
