"""投放模板 API（设计文档第 37.3 节）

Campaign Template 是整个系统最核心的业务对象：
用户配置一次模板，即可批量部署到多个广告账户（设计文档第 3.1 / 10 节）。
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_admin
from core.database import get_db
from core.enums import TemplateStatus
from models import CampaignTemplate

router = APIRouter(prefix="/api/v1/templates", tags=["投放模板"])


# ==================== 请求模型 ====================

class TemplateCreate(BaseModel):
    name: str = Field(..., description="模板名称，如 US Sales V1")
    objective: Optional[str] = Field(None, description="推广目标 OUTCOME_SALES / OUTCOME_TRAFFIC")
    buying_type: str = "AUCTION"
    special_ad_categories: List[str] = Field(default_factory=list)

    budget_type: str = Field("DAILY", description="DAILY / LIFETIME")
    daily_budget: Optional[float] = Field(None, description="日预算（USD）")
    lifetime_budget: Optional[float] = Field(None, description="总预算（USD）")

    bid_strategy: Optional[str] = None
    optimization_goal: Optional[str] = Field(None, description="如 LINK_CLICKS / OFFSITE_CONVERSIONS")
    billing_event: Optional[str] = Field(None, description="如 IMPRESSIONS / LINK_CLICKS")

    # Meta 易变参数统一放 JSON，避免频繁改表（设计文档第 10 节）
    targeting_json: Optional[Dict[str, Any]] = Field(None, description="定向：国家/年龄/性别/兴趣")
    placement_json: Optional[Dict[str, Any]] = Field(None, description="版位配置")
    creative_config_json: Optional[Dict[str, Any]] = Field(
        None,
        description="素材文案配置：{page_id, creatives:[{headline, primary_text, description, cta, landing_url, image_hash|video_id, asset_id}]}",
    )


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    buying_type: Optional[str] = None
    special_ad_categories: Optional[List[str]] = None
    budget_type: Optional[str] = None
    daily_budget: Optional[float] = None
    lifetime_budget: Optional[float] = None
    bid_strategy: Optional[str] = None
    optimization_goal: Optional[str] = None
    billing_event: Optional[str] = None
    targeting_json: Optional[Dict[str, Any]] = None
    placement_json: Optional[Dict[str, Any]] = None
    creative_config_json: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


# ==================== 路由 ====================

@router.get("")
def list_templates(
    status: Optional[str] = Query(None, description="按状态过滤 ACTIVE / DISABLED / ARCHIVED"),
    db: Session = Depends(get_db),
    _: object = Depends(get_current_active_user),
):
    """模板列表"""
    query = db.query(CampaignTemplate)
    if status:
        query = query.filter(CampaignTemplate.status == status)
    items = query.order_by(CampaignTemplate.created_at.desc()).all()
    return [t.to_dict() for t in items]


@router.post("", status_code=201)
def create_template(
    req: TemplateCreate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """创建投放模板"""
    if db.query(CampaignTemplate).filter(CampaignTemplate.name == req.name).first():
        raise HTTPException(status_code=400, detail=f"模板名称已存在: {req.name}")

    template = CampaignTemplate(
        id=uuid.uuid4().hex,
        **req.dict(exclude_none=False),
        status=TemplateStatus.ACTIVE.value,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template.to_dict()


@router.get("/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_active_user),
):
    """模板详情"""
    template = db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template.to_dict()


@router.patch("/{template_id}")
def update_template(
    template_id: str,
    req: TemplateUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """更新模板（仅更新传入字段）"""
    template = db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    for field, value in req.dict(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return template.to_dict()


@router.post("/{template_id}/clone", status_code=201)
def clone_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """复制模板（设计文档第 37.3 节）"""
    source = db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="模板不存在")

    clone = CampaignTemplate(
        id=uuid.uuid4().hex,
        name=f"{source.name} - 副本",
        objective=source.objective,
        buying_type=source.buying_type,
        special_ad_categories=source.special_ad_categories,
        budget_type=source.budget_type,
        daily_budget=source.daily_budget,
        lifetime_budget=source.lifetime_budget,
        bid_strategy=source.bid_strategy,
        optimization_goal=source.optimization_goal,
        billing_event=source.billing_event,
        targeting_json=source.targeting_json,
        placement_json=source.placement_json,
        creative_config_json=source.creative_config_json,
        status=TemplateStatus.ACTIVE.value,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return clone.to_dict()


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """删除模板（软删除：置为 ARCHIVED，保留历史实例映射）"""
    template = db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    template.status = TemplateStatus.ARCHIVED.value
    db.commit()
    return {"id": template_id, "status": template.status}
