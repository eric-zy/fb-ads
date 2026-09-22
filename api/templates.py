"""投放模板 API（设计文档第 37.3 节）

Campaign Template 是整个系统最核心的业务对象：
用户配置一次模板，即可批量部署到多个广告账户（设计文档第 3.1 / 10 节）。
"""
import uuid
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_admin
from core.database import get_db
from core.enums import TemplateStatus
from models import CampaignTemplate, MetaPage, User
from services.targeting_catalog import normalize_targeting, validate_audience_refs

router = APIRouter(prefix="/api/v1/templates", tags=["投放模板"])


def _validate_page_for_tenant(db: Session, creative_config: Optional[Dict[str, Any]]) -> None:
    page_id = (creative_config or {}).get("page_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="请选择已同步的 Facebook 页面")
    if not db.query(MetaPage).filter(
        MetaPage.page_id == str(page_id), MetaPage.status == "ACTIVE"
    ).first():
        raise HTTPException(status_code=400, detail="Facebook 页面未同步或不属于当前租户，请重新选择")


def _validate_delivery_config(values: Dict[str, Any]) -> None:
    objective = str(values.get("objective") or "").upper()
    if objective not in {"OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_APP_PROMOTION", "TRAFFIC", "REACH", "BRAND_AWARENESS", "VIDEO_VIEWS", "ENGAGEMENT", "LEAD_GENERATION", "CONVERSIONS", "LINK_CLICKS"}:
        raise HTTPException(status_code=400, detail="请选择有效的 Meta 广告系列目标")
    buying_type = str(values.get("buying_type") or "AUCTION").upper()
    if buying_type != "AUCTION":
        raise HTTPException(status_code=400, detail="当前系统只支持 AUCTION 购买类型")
    bid_strategy = str(values.get("bid_strategy") or "").upper()
    bidding = (values.get("creative_config_json") or {}).get("bidding") or {}
    if bid_strategy not in {"", "LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS"}:
        raise HTTPException(status_code=400, detail="请选择有效的 Meta 出价策略")
    if bid_strategy in {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"} and (bidding.get("bid_amount") is None or float(bidding["bid_amount"]) <= 0):
        raise HTTPException(status_code=400, detail=f"出价策略 {bid_strategy} 必须配置 bid_amount")
    if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" and not isinstance(bidding.get("bid_constraints"), dict):
        raise HTTPException(status_code=400, detail="最低 ROAS 出价必须配置 bid_constraints")

    budget_type = str(values.get("budget_type") or "DAILY").upper()
    if budget_type not in {"DAILY", "LIFETIME"}:
        raise HTTPException(status_code=400, detail="budget_type 只能是 DAILY 或 LIFETIME")
    budget = values.get("lifetime_budget") if budget_type == "LIFETIME" else values.get("daily_budget")
    if budget is None or float(budget) <= 0:
        raise HTTPException(status_code=400, detail="模板预算必须大于 0")

    targeting = values.get("targeting_json") or {}
    try:
        # 语言和自定义受众统一走目录/引用校验；这里不访问 Meta，账户级
        # 归属和状态由发布预检继续校验。
        normalize_targeting(targeting)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    countries = ((targeting.get("geo_locations") or {}).get("countries") or [])
    if not countries:
        raise HTTPException(status_code=400, detail="定向必须至少选择一个国家")
    if targeting.get("age_min") is not None and targeting.get("age_max") is not None and int(targeting["age_min"]) > int(targeting["age_max"]):
        raise HTTPException(status_code=400, detail="年龄范围无效：最小年龄不能大于最大年龄")

    config = values.get("creative_config_json") or {}
    if budget_type == "LIFETIME" and not (config.get("schedule") or {}).get("end_time"):
        raise HTTPException(status_code=400, detail="总预算模板必须配置 schedule.end_time")
    optimization_goal = str(values.get("optimization_goal") or "LINK_CLICKS").upper()
    objective = str(values.get("objective") or "OUTCOME_TRAFFIC").upper()
    if objective == "OUTCOME_SALES" and optimization_goal in {"LINK_CLICKS", "LANDING_PAGE_VIEWS"}:
        raise HTTPException(status_code=400, detail="OUTCOME_SALES 不支持 LINK_CLICKS/LANDING_PAGE_VIEWS；请改用 OUTCOME_TRAFFIC，或配置 OFFSITE_CONVERSIONS 及 promoted_object")
    # Pixel/Dataset 只在发布预检时按 optimization_goal 判断。模板可以先保存为
    # 可复用草稿，避免把 Pixel 误设为所有推广目标的全局必填项；真正发布时由
    # JobService.preflight_campaign 返回明确的 TRACKING_ASSET_REQUIRED。

    audience_keys = {
        "custom_audiences", "excluded_custom_audiences",
        "lookalike_audiences", "excluded_audiences",
    }
    for key in audience_keys:
        if targeting.get(key) is not None:
            try:
                validate_audience_refs(targeting.get(key), key)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    if targeting.get("languages") is not None and not isinstance(targeting.get("languages"), list):
        raise HTTPException(status_code=400, detail="定向字段 languages 必须是数组")
    placements = values.get("placement_json") or {}
    for key in ("publisher_platforms", "facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions"):
        if placements.get(key) is not None and not isinstance(placements.get(key), list):
            raise HTTPException(status_code=400, detail=f"版位字段 {key} 必须是数组")
    # 多 AdSet 的每组配置必须在保存阶段完成校验，避免 Meta API 执行到一半才失败。
    for index, adset in enumerate(config.get("adsets") or [], 1):
        if not isinstance(adset, dict):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 配置必须是对象")
        if adset.get("budget") is not None and float(adset["budget"]) <= 0:
            raise HTTPException(status_code=400, detail=f"广告组 {index} 预算必须大于 0")
        adset_targeting = adset.get("targeting") or {}
        try:
            normalize_targeting(adset_targeting)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"广告组 {index}：{exc}") from exc
        adset_geo = (adset_targeting.get("geo_locations") or {}).get("countries") or []
        if not adset_geo:
            raise HTTPException(status_code=400, detail=f"广告组 {index} 至少配置一个国家/地区")
        if adset_targeting.get("age_min") is not None and adset_targeting.get("age_max") is not None and int(adset_targeting["age_min"]) > int(adset_targeting["age_max"]):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 年龄范围无效")
        automation = adset_targeting.get("targeting_automation") or {"advantage_audience": adset.get("advantage_audience", 1)}
        if automation.get("advantage_audience") not in (0, 1):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 的 advantage_audience 必须是 0 或 1")
        adset_strategy = str(adset.get("bid_strategy") or bid_strategy).upper()
        adset_amount = adset.get("bid_amount")
        if adset_strategy in {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"} and (adset_amount is None or float(adset_amount) <= 0):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 的 {adset_strategy} 必须配置 bid_amount")
        adset_placements = adset.get("placement") or {}
        for key in ("publisher_platforms", "facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions"):
            if adset_placements.get(key) is not None and not isinstance(adset_placements.get(key), list):
                raise HTTPException(status_code=400, detail=f"广告组 {index} 的版位字段 {key} 必须是数组")
        # 广告组级事件源同样在发布预检阶段校验，模板保存不拦截。
    creative_format = str(config.get("creative_format") or "MULTI_AD").upper()
    delivery = config.get("delivery") or {}
    split_level = str(delivery.get("split_level") or "AD").upper()
    combination_mode = str(delivery.get("combination_mode") or "ACCOUNT_X_ADSET_X_CREATIVE").upper()
    if split_level not in {"AD", "ADSET"}:
        raise HTTPException(status_code=400, detail="当前支持按 AD 或 ADSET 拆分；按 CAMPAIGN 拆分将在后续版本开放")
    if combination_mode != "ACCOUNT_X_ADSET_X_CREATIVE":
        raise HTTPException(status_code=400, detail="当前仅支持账户 × 广告组 × 素材组合方式")
    if creative_format == "CAROUSEL" and split_level != "AD":
        raise HTTPException(status_code=400, detail="轮播广告只能按 AD 生成，一个轮播组合对应一个广告")
    if creative_format == "CAROUSEL":
        creatives = config.get("carousel_cards") or []
        if not 2 <= len(creatives) <= 10:
            raise HTTPException(status_code=400, detail="轮播广告必须配置 2-10 张图片卡片")
    else:
        creatives = config.get("creatives") or []
    if not creatives:
        raise HTTPException(status_code=400, detail="至少配置一个广告创意")
    allowed_cta = {"LEARN_MORE", "SHOP_NOW", "SIGN_UP", "BOOK_NOW", "DOWNLOAD", "GET_OFFER", "CONTACT_US", "SUBSCRIBE", "APPLY_NOW", "WATCH_MORE", "MESSAGE_PAGE", "ORDER_NOW", "GET_QUOTE"}
    for index, creative in enumerate(creatives, 1):
        asset_type = str(creative.get("asset_type") or "image").lower()
        if creative_format == "CAROUSEL" and asset_type != "image":
            raise HTTPException(status_code=400, detail=f"轮播卡片 {index} 必须使用图片素材")
        if asset_type == "image" and creative_format != "CAROUSEL" and not (
            creative.get("image_hash") or creative.get("asset_id")
        ):
            raise HTTPException(status_code=400, detail=f"创意 {index} 缺少图片素材")
        if creative_format == "CAROUSEL" and not creative.get("asset_id") and not creative.get("image_hash"):
            raise HTTPException(status_code=400, detail=f"轮播卡片 {index} 缺少素材")
        # 模板只保存素材库的 asset_id；素材上传到具体 Meta 广告账户属于投放前置步骤，
        # 不应要求创建模板时已经存在 account-scoped video_id。发布前的
        # JobService.preflight_campaign 会继续校验目标账户是否有 READY 绑定。
        if asset_type == "video" and not (creative.get("video_id") or creative.get("asset_id")):
            raise HTTPException(status_code=400, detail=f"创意 {index} 缺少视频素材或素材 ID")
        if creative.get("instagram_actor_id") and not str(creative["instagram_actor_id"]).strip():
            raise HTTPException(status_code=400, detail=f"创意 {index} 的 Instagram 身份无效")
        if creative.get("url_tags") and not isinstance(creative["url_tags"], str):
            raise HTTPException(status_code=400, detail=f"创意 {index} 的 URL 参数必须是字符串")
        landing_url = str(creative.get("landing_url") or "")
        if asset_type != "video" or landing_url:
            parsed = urlparse(landing_url)
            if not parsed.scheme in {"http", "https"} or not parsed.netloc:
                raise HTTPException(status_code=400, detail=f"创意 {index} 的落地页必须是有效的 http/https URL")
        if creative.get("cta") and str(creative["cta"]).upper() not in allowed_cta:
            raise HTTPException(status_code=400, detail=f"创意 {index} 的行动按钮不受 Meta 支持")


# ==================== 请求模型 ====================

class TemplateCreate(BaseModel):
    name: str = Field(..., description="模板名称，如 US Sales V1")
    objective: Optional[str] = Field(None, description="推广目标 OUTCOME_SALES / OUTCOME_TRAFFIC")
    buying_type: str = "AUCTION"
    is_adset_budget_sharing_enabled: bool = False
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
    is_adset_budget_sharing_enabled: Optional[bool] = None
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
    query = db.query(CampaignTemplate).filter(CampaignTemplate.is_temporary.is_(False))
    if status:
        query = query.filter(CampaignTemplate.status == status)
    items = query.order_by(CampaignTemplate.created_at.desc()).all()
    return [t.to_dict() for t in items]


@router.post("", status_code=201)
def create_template(
    req: TemplateCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    """创建投放模板"""
    if db.query(CampaignTemplate).filter(CampaignTemplate.name == req.name).first():
        raise HTTPException(status_code=400, detail=f"模板名称已存在: {req.name}")

    _validate_page_for_tenant(db, req.creative_config_json)
    _validate_delivery_config(req.dict(exclude_none=False))
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
    _: User = Depends(require_admin),
):
    """更新模板（仅更新传入字段）"""
    template = db.query(CampaignTemplate).filter(CampaignTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    values = req.dict(exclude_unset=True)
    merged = template.to_dict()
    merged.update(values)
    _validate_delivery_config(merged)
    if "creative_config_json" in values:
        _validate_page_for_tenant(db, values["creative_config_json"])
    for field, value in values.items():
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
        is_adset_budget_sharing_enabled=source.is_adset_budget_sharing_enabled,
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
