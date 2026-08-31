"""Job Center API（设计文档第 37.4 / 37.5 / 37.6 节）

批量投放全部走异步 Job：提交后立刻返回 job_id，前端轮询 GET /api/v1/jobs/{id}。

    HTTP Request → Create Job → Return job_id → Worker Async Execute
                                                  （原则二：任务异步）
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from core.enums import ActionType, InstanceStatus
from core.logger import logger
from models import CampaignInstance
from services.job_service import JobService

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Center"])


# ==================== 请求模型 ====================

class CampaignCreateRequest(BaseModel):
    """设计文档第 38 节请求体"""
    template_id: str = Field(..., description="投放模板 ID")
    ad_account_ids: List[str] = Field(..., description="目标广告账户 id 列表")
    budget_override: Optional[float] = Field(None, description="覆盖模板预算（USD/天）")
    status: str = Field("PAUSED", description="创建后状态，默认 PAUSED，避免直接产生花费")


class BudgetUpdateRequest(BaseModel):
    """设计文档第 22 节：按模板批量改预算"""
    template_id: str
    ad_account_ids: Optional[List[str]] = Field(
        None, description="不传则取该模板已部署的全部账户"
    )
    budget_override: float = Field(..., description="新预算（USD/天）")


class StatusChangeRequest(BaseModel):
    template_id: str
    ad_account_ids: Optional[List[str]] = Field(
        None, description="不传则取该模板已部署的全部账户"
    )


class ScheduleCampaignRequest(BaseModel):
    """定时投放（复用 Job 体系，由 Celery eta 延迟派发）"""
    template_id: str = Field(..., description="投放模板 ID")
    ad_account_ids: List[str] = Field(..., description="目标广告账户 id 列表")
    budget_override: Optional[float] = Field(None, description="覆盖模板预算（USD/天）")
    status: str = Field("PAUSED", description="创建后状态")
    scheduled_at: str = Field(
        ...,
        description="计划执行时间，ISO 8601（如 2026-08-30T10:00:00Z 或 2026-08-30T18:00:00+08:00），必须晚于当前时间",
    )


def _parse_scheduled_at(value: str) -> datetime:
    """解析并校验计划执行时间，统一转换为 UTC naive datetime"""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="scheduled_at 格式错误，应为 ISO 8601（如 2026-08-30T10:00:00Z）",
        )

    # 带时区则换算到 UTC；naive 时间直接按 UTC 处理
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    if dt <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="scheduled_at 必须晚于当前时间")

    return dt


# ==================== 工具 ====================

def _resolve_accounts(
    db: Session, template_id: str, ad_account_ids: Optional[List[str]]
) -> List[str]:
    """未显式指定账户时，从实例映射表反查该模板已部署的所有账户

    这正是 campaign_instances 的价值（设计文档第 22 节）：
        SELECT * FROM campaign_instances WHERE template_id = 100
    """
    if ad_account_ids:
        return ad_account_ids
    rows = (
        db.query(CampaignInstance.ad_account_id)
        .filter(
            CampaignInstance.template_id == template_id,
            CampaignInstance.status != InstanceStatus.DELETED.value,
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _submit(
    db: Session,
    *,
    template_id: str,
    ad_account_ids: List[str],
    action_type: ActionType,
    params: dict,
    created_by,
    scheduled_at: Optional[datetime] = None,
) -> dict:
    """统一提交入口：建 Job → 派发 → 立即返回"""
    service = JobService(db)
    try:
        job = service.create_job(
            template_id=template_id,
            ad_account_ids=ad_account_ids,
            action_type=action_type,
            params=params,
            created_by=getattr(created_by, "id", None),
            scheduled_at=scheduled_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "job_id": job.id,
        "status": job.status,
        "total_accounts": job.total_accounts,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
    }


# ==================== 批量投放 ====================

@router.post("/campaign-create")
def create_campaign_batch(
    req: CampaignCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """批量创建 Campaign / AdSet / Ad（异步）"""
    return _submit(
        db,
        template_id=req.template_id,
        ad_account_ids=req.ad_account_ids,
        action_type=ActionType.CREATE,
        params={
            "budget_override": req.budget_override,
            "status": req.status,
        },
        created_by=current_user,
    )


# ==================== 定时投放（Job + Celery eta） ====================

@router.post("/schedule")
def schedule_campaign_batch(
    req: ScheduleCampaignRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """创建定时投放任务

    与 campaign-create 的唯一区别是传入 scheduled_at：
    Job 先以 QUEUED 状态落库，由 Celery 在指定时间触发执行。
    """
    scheduled_at = _parse_scheduled_at(req.scheduled_at)

    return _submit(
        db,
        template_id=req.template_id,
        ad_account_ids=req.ad_account_ids,
        action_type=ActionType.CREATE,
        params={
            "budget_override": req.budget_override,
            "status": req.status,
        },
        created_by=current_user,
        scheduled_at=scheduled_at,
    )


@router.get("/scheduled")
def list_scheduled_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """待执行的定时任务列表（按计划执行时间升序）"""
    jobs = JobService(db).list_scheduled_jobs(limit=limit)
    return [j.to_dict() for j in jobs]


@router.post("/{job_id}/dispatch-now")
def dispatch_job_now(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """把定时任务提前为立即执行（会撤销原定的延迟投递）"""
    job = JobService(db).dispatch_now(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()


# ==================== 批量预算 / 启停 ====================

@router.post("/budget-update")
def update_budget_batch(
    req: BudgetUpdateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """批量修改预算（设计文档第 22 节）"""
    accounts = _resolve_accounts(db, req.template_id, req.ad_account_ids)
    if not accounts:
        raise HTTPException(status_code=400, detail="该模板下没有已部署的广告账户")

    return _submit(
        db,
        template_id=req.template_id,
        ad_account_ids=accounts,
        action_type=ActionType.UPDATE_BUDGET,
        params={"budget_override": req.budget_override},
        created_by=current_user,
    )


@router.post("/pause")
def pause_batch(
    req: StatusChangeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """批量暂停"""
    accounts = _resolve_accounts(db, req.template_id, req.ad_account_ids)
    if not accounts:
        raise HTTPException(status_code=400, detail="该模板下没有已部署的广告账户")

    return _submit(
        db,
        template_id=req.template_id,
        ad_account_ids=accounts,
        action_type=ActionType.PAUSE,
        params={},
        created_by=current_user,
    )


@router.post("/enable")
def enable_batch(
    req: StatusChangeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """批量启用"""
    accounts = _resolve_accounts(db, req.template_id, req.ad_account_ids)
    if not accounts:
        raise HTTPException(status_code=400, detail="该模板下没有已部署的广告账户")

    return _submit(
        db,
        template_id=req.template_id,
        ad_account_ids=accounts,
        action_type=ActionType.ENABLE,
        params={},
        created_by=current_user,
    )


# ==================== 任务查询与控制 ====================

@router.get("")
def list_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """任务列表"""
    jobs = JobService(db).list_jobs(limit=limit, status=status)
    return [j.to_dict() for j in jobs]


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """任务详情（前端轮询进度：成功 / 失败 / 执行中各多少）"""
    detail = JobService(db).get_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail="任务不存在")
    return detail


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """只重跑失败的子项（设计文档第 30 节）"""
    count = JobService(db).retry_failed(job_id)
    if count == 0:
        raise HTTPException(status_code=400, detail="没有可重试的失败子项")
    return {"job_id": job_id, "retried": count}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    """取消任务"""
    job = JobService(db).cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()
