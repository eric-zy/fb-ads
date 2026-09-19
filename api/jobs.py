"""Job Center API（设计文档第 37.4 / 37.5 / 37.6 节）

批量投放全部走异步 Job：提交后立刻返回 job_id，前端轮询 GET /api/v1/jobs/{id}。

    HTTP Request → Create Job → Return job_id → Worker Async Execute
                                                  （原则二：任务异步）
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
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
from models import CampaignInstance, CampaignTemplate, CampaignJob, CampaignJobItem, PublishPreview, User
from services.account_access import accessible_account_ids

def _publisher_info(db: Session, user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"id": user_id, "username": "已删除用户", "email": None}
    return {"id": user.id, "username": user.username, "email": user.email}
from core.enums import TemplateStatus
from services.job_service import JobDispatchError, JobService

router = APIRouter(prefix="/api/v1/jobs", tags=["Job Center"])


def _scope_jobs(query, current_user):
    """限制 Job Center 到当前生效租户；平台管理员未切租户时可跨租户审计。"""
    tenant_id = effective_tenant_id(current_user)
    if tenant_id:
        return query.filter(CampaignJob.tenant_id == tenant_id)
    if getattr(current_user, "is_platform_admin", lambda: False)():
        return query
    raise HTTPException(status_code=403, detail="当前账号未绑定租户")


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
    preview_id: Optional[str] = Field(None, description="发布前预览快照 ID")
    snapshot_hash: Optional[str] = Field(None, description="发布前预览快照哈希")
    idempotency_key: Optional[str] = Field(None, max_length=128, description="客户端幂等键")

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
    except JobDispatchError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "job_id": job.id,
        "status": job.status,
        "template_id": job.template_id,
        "source": (job.params or {}).get("source", "TEMPLATE"),
        "total_accounts": job.total_accounts,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "rejected_accounts": (job.params or {}).get("rejected_accounts", []),
        "preview_id": job.preview_id,
    }


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _create_preview(
    db: Session,
    req: CampaignPreflightRequest,
    result: dict,
    template_id: str,
    current_user: User,
) -> PublishPreview:
    request_snapshot = {
        "template_id": template_id,
        "source": req.source or ("TEMPLATE" if req.template_id else "DIRECT"),
        "inline_config": req.inline_config,
        "ad_account_ids": sorted(set(req.ad_account_ids or [])),
        "budget_override": req.budget_override,
        "status": req.status,
        "sinan_promotion_id": req.sinan_promotion_id,
        "access_business_ids": req.access_business_ids or {},
    }
    snapshot_hash = _canonical_hash({"request": request_snapshot, "result": result})
    preview = PublishPreview(
        id=uuid.uuid4().hex,
        created_by=current_user.id,
        template_id=template_id,
        source=request_snapshot["source"],
        request_snapshot=request_snapshot,
        result_snapshot=result,
        account_ids=sorted(set(result.get("ready_account_ids") or [])),
        snapshot_hash=snapshot_hash,
        status="READY",
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db.add(preview)
    db.commit()
    db.refresh(preview)
    return preview


def _validate_preview_for_submit(
    db: Session,
    req: CampaignCreateRequest,
    current_user: User,
) -> PublishPreview:
    if not req.preview_id or not req.snapshot_hash:
        raise HTTPException(status_code=400, detail="提交前必须先完成预览校验")
    preview = (
        db.query(PublishPreview)
        .filter(PublishPreview.id == req.preview_id)
        .first()
    )
    if not preview or preview.created_by != current_user.id and not current_user.is_admin():
        raise HTTPException(status_code=404, detail="预览不存在或无权提交")
    if not preview.is_valid():
        if preview.status == "READY":
            preview.status = "EXPIRED"
            db.commit()
        raise HTTPException(status_code=409, detail="预览已过期，请重新执行预览")
    if req.snapshot_hash != preview.snapshot_hash:
        raise HTTPException(status_code=409, detail="预览内容已变化，请重新执行预览")
    expected = sorted(set(preview.account_ids or []))
    actual = sorted(set(req.ad_account_ids or []))
    if expected != actual:
        raise HTTPException(status_code=409, detail="提交账户与预览账户不一致，请重新执行预览")
    visible = accessible_account_ids(db, current_user)
    if visible is not None and any(account_id not in visible for account_id in expected):
        raise HTTPException(status_code=403, detail="提交账户权限已变化，请重新选择账户")
    if req.template_id and req.template_id != preview.template_id:
        raise HTTPException(status_code=409, detail="提交模板与预览模板不一致")
    return preview


# ==================== 批量投放 ====================

@router.post("/campaign-preflight")
def campaign_preflight(req: CampaignPreflightRequest, db: Session = Depends(get_db), current_user=Depends(require_permission("job:create"))):
    """发布前检查；不调用 Meta 写接口。直接配置会先标准化为内部配置。"""
    template_id = _ensure_template(db, req, effective_tenant_id(current_user))
    result = JobService(db).preflight_campaign(template_id, req.ad_account_ids, req.budget_override, req.status, created_by=current_user.id)
    result["source"] = req.source or ("TEMPLATE" if req.template_id else "DIRECT")
    result["template_id"] = template_id
    if result.get("passed"):
        preview = _create_preview(db, req, result, template_id, current_user)
        result["preview_id"] = preview.id
        result["snapshot_hash"] = preview.snapshot_hash
        result["expires_at"] = preview.expires_at.isoformat()
    return result

@router.post("/campaign-create")
def create_campaign_batch(
    req: CampaignCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:create")),
):
    """批量创建 Campaign / AdSet / Ad（异步）"""
    logger.info(
        "[JobAPI] campaign-create received accounts=%s template_id=%s source=%s",
        len(req.ad_account_ids),
        req.template_id or "DIRECT",
        req.source or ("TEMPLATE" if req.template_id else "DIRECT"),
    )
    preview = _validate_preview_for_submit(db, req, current_user)
    template_id = _ensure_template(db, req, effective_tenant_id(current_user))
    result = _submit(
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
            "_preview_id": preview.id,
            "_idempotency_key": req.idempotency_key or f"publish:{preview.id}",
        },
        created_by=current_user,
    )
    preview.status = "SUBMITTED"
    preview.submitted_at = datetime.utcnow()
    preview.submitted_job_id = result["job_id"]
    db.commit()
    logger.info(
        "[JobAPI] campaign-create submitted job_id=%s accounts=%s status=%s",
        result["job_id"],
        result["total_accounts"],
        result["status"],
    )
    return result


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
    visible = accessible_account_ids(db, current_user)
    for job in jobs:
        if visible is not None and job.created_by != current_user.id and not any(item.ad_account_id in visible for item in job.items):
            continue
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
    visible = accessible_account_ids(db, current_user)
    if visible is not None and owned.created_by != current_user.id and not any(item.ad_account_id in visible for item in owned.items):
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    try:
        job = JobService(db).dispatch_now(job_id)
    except JobDispatchError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
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
    query = _scope_jobs(db.query(CampaignJob), current_user)
    if status:
        query = query.filter(CampaignJob.status == status)
    jobs = query.order_by(CampaignJob.created_at.desc()).limit(limit).all()
    visible = accessible_account_ids(db, current_user)
    result = []
    for job in jobs:
        if visible is not None and job.created_by != current_user.id and not any(item.ad_account_id in visible for item in job.items):
            continue
        payload = job.to_dict()
        if visible is not None:
            items = [item for item in job.items if item.ad_account_id in visible]
            payload["total_accounts"] = len(items)
            payload["success_count"] = sum(item.status in ("SUCCESS", "SKIPPED") for item in items)
            payload["failed_count"] = sum(item.status == "FAILED" for item in items)
        payload["publisher"] = _publisher_info(db, job.created_by)
        result.append(payload)
    return result


@router.get("/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """任务详情（前端轮询进度：成功 / 失败 / 执行中各多少）"""
    owned = _scope_jobs(db.query(CampaignJob), current_user).filter(CampaignJob.id == job_id).first()
    if not owned:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    visible = accessible_account_ids(db, current_user)
    if visible is not None and owned.created_by != current_user.id and not any(item.ad_account_id in visible for item in owned.items):
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    detail = JobService(db).get_job_detail(job_id)
    if not detail:
        raise HTTPException(status_code=404, detail="任务不存在")
    if visible is not None:
        detail["items"] = [item for item in detail["items"] if item["ad_account_id"] in visible]
        detail["total_accounts"] = len(detail["items"])
        detail["success_count"] = sum(item["status"] in ("SUCCESS", "SKIPPED") for item in detail["items"])
        detail["failed_count"] = sum(item["status"] == "FAILED" for item in detail["items"])
    detail["publisher"] = _publisher_info(db, owned.created_by)
    return detail


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:retry")),
):
    """只重跑失败的子项（设计文档第 30 节）"""
    job = _scope_jobs(db.query(CampaignJob), current_user).filter(CampaignJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    visible = accessible_account_ids(db, current_user)
    if visible is not None and job.created_by != current_user.id and not any(item.ad_account_id in visible for item in job.items):
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    count = JobService(db).retry_failed(job_id)
    if count == 0:
        raise HTTPException(status_code=400, detail="没有可重试的失败子项")
    return {"job_id": job_id, "retried": count}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("job:cancel")),
):
    """取消任务"""
    existing = _scope_jobs(db.query(CampaignJob), current_user).filter(CampaignJob.id == job_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="任务不存在")
    visible = accessible_account_ids(db, current_user)
    if visible is not None and existing.created_by != current_user.id and not any(item.ad_account_id in visible for item in existing.items):
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    job = JobService(db).cancel_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()
