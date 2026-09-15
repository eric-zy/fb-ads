"""Job Center API（设计文档第 37.4 / 37.5 / 37.6 节）

批量投放全部走异步 Job：提交后立刻返回 job_id，前端轮询 GET /api/v1/jobs/{id}。

    HTTP Request → Create Job → Return job_id → Worker Async Execute
                                                  （原则二：任务异步）
"""
from datetime import datetime, timezone
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_permission
from core.database import get_db
from core.enums import ActionType, InstanceStatus
from core.logger import logger
from core.tenant import effective_tenant_id
from models import CampaignInstance, CampaignTemplate, CampaignJob, User

def _publisher_info(db: Session, user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"id": user_id, "username": "已删除用户", "email": None}
    return {"id": user.id, "username": user.username, "email": user.email}
from core.enums import TemplateStatus
from services.job_service import JobService

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Center"])


# ==================== 请求模型 ====================

class CampaignCreateRequest(BaseModel):
    """设计文档第 38 节请求体"""
    template_id: Optional[str] = Field(None, description="投放模板 ID；直接配置时可不传")
    inline_config: Optional[dict] = Field(None, description="不使用模板时的完整投放配置")
    save_as_template: bool = Field(False, description="是否将直接配置另存为投放模板")
    template_name: Optional[str] = Field(None, description="另存模板名称")
    source: Optional[str] = Field(None, description="投放来源：TEMPLATE / DIRECT")
    ad_account_ids: List[str] = Field(..., description="目标广告账户 id 列表")
    budget_override: Optional[float] = Field(None, description="覆盖模板预算（USD/天）")
    status: str = Field("PAUSED", description="创建后状态，默认 PAUSED，避免直接产生花费")
    sinan_promotion_id: Optional[str] = None
    access_business_ids: Optional[dict[str, str]] = Field(
        None, description="按本地广告账户 ID 指定本次发布使用的 BM"
    )

class CampaignPreflightRequest(CampaignCreateRequest):
    pass


def _ensure_template(db: Session, req: CampaignCreateRequest, tenant_id: Optional[str] = None) -> str:
    """把模板请求和直接配置请求统一成现有发布器可消费的模板。"""
    if req.template_id:
        template = db.query(CampaignTemplate).filter(CampaignTemplate.id == req.template_id).first()
        if not template or (tenant_id and template.tenant_id != tenant_id):
            raise HTTPException(status_code=404, detail="投放模板不存在或无权访问")
        return template.id
    if req.save_as_template and not str(req.template_name or "").strip():
        raise HTTPException(status_code=400, detail="已勾选保存为投放模板，请填写模板名称")
    config = req.inline_config or {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="inline_config 必须是对象")
    if not config:
        raise HTTPException(status_code=400, detail="未选择模板时必须提供直接投放配置")
    name = req.template_name or config.get("name") or f"直接投放-{datetime.utcnow():%Y%m%d%H%M%S}"
    objective = str(config.get("objective") or "").upper()
    if objective not in {"OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_APP_PROMOTION"}:
        raise HTTPException(status_code=400, detail="推广目标无效，请选择 Meta 支持的 OUTCOME_* 目标")
    daily_budget = config.get("daily_budget") or config.get("budget")
    if daily_budget is None or float(daily_budget) <= 0:
        raise HTTPException(status_code=400, detail="直接配置的日预算必须大于 0")
    page_id = str(config.get("page_id") or "").strip()
    if not page_id:
        raise HTTPException(status_code=400, detail="直接配置必须选择 Facebook Page")
    adsets = config.get("adsets")
    if not isinstance(adsets, list) or not adsets:
        raise HTTPException(status_code=400, detail="至少需要配置一个广告组")
    for index, adset in enumerate(adsets, 1):
        if not isinstance(adset, dict) or not str(adset.get("name") or "").strip():
            raise HTTPException(status_code=400, detail=f"广告组 {index} 缺少名称")
        if float(adset.get("budget") or 0) <= 0:
            raise HTTPException(status_code=400, detail=f"广告组 {index} 预算必须大于 0")
        strategy = str(adset.get("bid_strategy") or config.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP").upper()
        if strategy in {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"} and not adset.get("bid_amount"):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 的出价策略需要填写出价金额")
    creatives = config.get("creatives") or []
    if not isinstance(creatives, list) or not creatives:
        raise HTTPException(status_code=400, detail="至少需要配置一个广告创意")
    for index, creative in enumerate(creatives, 1):
        if not isinstance(creative, dict) or not creative.get("asset_id"):
            raise HTTPException(status_code=400, detail=f"广告创意 {index} 缺少素材 ID")
        if not str(creative.get("primary_text") or "").strip():
            raise HTTPException(status_code=400, detail=f"广告创意 {index} 缺少主文案")
        if not str(creative.get("landing_url") or "").startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail=f"广告创意 {index} 的落地页必须是 http/https 地址")
    fields = {
        "name": name,
        "objective": objective,
        "buying_type": config.get("buying_type", "AUCTION"),
        "is_adset_budget_sharing_enabled": bool(config.get("is_adset_budget_sharing_enabled", False)),
        "special_ad_categories": config.get("special_ad_categories", []),
        "budget_type": config.get("budget_type", "DAILY"),
        "daily_budget": daily_budget,
        "lifetime_budget": config.get("lifetime_budget"),
        "bid_strategy": config.get("bid_strategy"),
        "optimization_goal": config.get("optimization_goal"),
        "billing_event": config.get("billing_event"),
        "targeting_json": config.get("targeting_json") or config.get("targeting"),
        "placement_json": config.get("placement_json") or config.get("placement"),
        "creative_config_json": config.get("creative_config_json") or {
            "page_id": config.get("page_id"),
            "creatives": config.get("creatives", []),
            "adsets": config.get("adsets", []),
        },
    }
    if not fields["name"]:
        raise HTTPException(status_code=400, detail="直接配置必须提供投放名称")
    template = CampaignTemplate(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        status=TemplateStatus.ACTIVE.value,
        is_temporary=not req.save_as_template,
        **fields,
    )
    db.add(template)
    db.commit()
    return template.id


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
    access_business_ids: Optional[dict[str, str]] = Field(
        None, description="按本地广告账户 ID 指定本次发布使用的 BM"
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
        "template_id": job.template_id,
        "source": (job.params or {}).get("source", "TEMPLATE"),
        "total_accounts": job.total_accounts,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "rejected_accounts": (job.params or {}).get("rejected_accounts", []),
    }


# ==================== 批量投放 ====================

@router.post("/campaign-preflight")
def campaign_preflight(req: CampaignPreflightRequest, db: Session = Depends(get_db), current_user=Depends(require_permission("job:create"))):
    """发布前检查；不调用 Meta 写接口。直接配置会先标准化为内部配置。"""
    template_id = _ensure_template(db, req, effective_tenant_id(current_user))
    result = JobService(db).preflight_campaign(template_id, req.ad_account_ids, req.budget_override, req.status, created_by=current_user.id)
    result["source"] = req.source or ("TEMPLATE" if req.template_id else "DIRECT")
    result["template_id"] = template_id
    return result

@router.post("/campaign-create")
def create_campaign_batch(
    req: CampaignCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:create")),
):
    """批量创建 Campaign / AdSet / Ad（异步）"""
    template_id = _ensure_template(db, req, effective_tenant_id(current_user))
    return _submit(
        db,
        template_id=template_id,
        ad_account_ids=req.ad_account_ids,
        action_type=ActionType.CREATE,
        params={
            "budget_override": req.budget_override,
            "status": req.status,
            "sinan_promotion_id": req.sinan_promotion_id,
            "access_business_ids": req.access_business_ids or {},
            "source": req.source or ("TEMPLATE" if req.template_id else "DIRECT"),
            "save_as_template": req.save_as_template,
        },
        created_by=current_user,
    )


# ==================== 定时投放（Job + Celery eta） ====================

@router.post("/schedule")
def schedule_campaign_batch(
    req: ScheduleCampaignRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:create")),
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
            "access_business_ids": req.access_business_ids or {},
        },
        created_by=current_user,
        scheduled_at=scheduled_at,
    )


@router.get("/scheduled")
def list_scheduled_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:create")),
):
    """待执行的定时任务列表（按计划执行时间升序）"""
    jobs = JobService(db).list_scheduled_jobs(limit=limit)
    result = []
    for job in jobs:
        payload = job.to_dict()
        payload["publisher"] = _publisher_info(db, job.created_by)
        result.append(payload)
    return result


@router.post("/{job_id}/dispatch-now")
def dispatch_job_now(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:create")),
):
    """把定时任务提前为立即执行（会撤销原定的延迟投递）"""
    owned = db.query(CampaignJob).filter(CampaignJob.id == job_id, CampaignJob.tenant_id == effective_tenant_id(current_user)).first()
    if not owned:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
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
    current_user=Depends(get_current_active_user),
):
    """任务列表"""
    jobs = JobService(db).list_jobs(limit=limit, status=status)
    return [j.to_dict() for j in jobs]


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """任务详情（前端轮询进度：成功 / 失败 / 执行中各多少）"""
    owned = db.query(CampaignJob).filter(CampaignJob.id == job_id, CampaignJob.tenant_id == effective_tenant_id(current_user)).first()
    if not owned:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    detail = JobService(db).get_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail="任务不存在")
    detail["publisher"] = _publisher_info(db, owned.created_by)
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
