"""投放模板 API（设计文档第 37.3 节）

Campaign Template 是整个系统最核心的业务对象：
用户配置一次模板，即可批量部署到多个广告账户（设计文档第 3.1 / 10 节）。
"""
import uuid
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from core.enums import TemplateStatus
from services.business_access import owned_query, tenant_required
from models import CampaignTemplate, MetaPage, TemplateCollaborator, User
from services.template_access import (
    TEMPLATE_ADMIN,
    TEMPLATE_EDITOR,
    TEMPLATE_OWNER,
    TEMPLATE_VIEWER,
    can_edit_template,
    can_manage_template_access,
    template_access_level,
    template_query,
)
from services.creative_format import normalize_creative_format
from services.meta_creative_options import normalize_cta
from services.meta_delivery_rules import default_optimization_goal, filter_unused_tracking_assets, objective_optimization_preflight_errors
from services.targeting_catalog import (
    normalize_targeting,
    placement_preflight_errors,
    targeting_preflight_errors,
    validate_audience_refs,
)

router = APIRouter(prefix="/api/v1/templates", tags=["投放模板"])


def _template_response(
    template: CampaignTemplate,
    db: Optional[Session] = None,
    current_user: Optional[User] = None,
) -> Dict[str, Any]:
    """返回模板时再次过滤历史数据中的无关事件源字段。"""

    result = template.to_dict()
    goal = template.optimization_goal or default_optimization_goal(template.objective)
    result["creative_config_json"] = filter_unused_tracking_assets(
        goal,
        result.get("creative_config_json"),
    )
    if db is not None and current_user is not None:
        access_level = template_access_level(db, template, current_user)
        result["access_level"] = access_level
        result["can_edit"] = access_level in {TEMPLATE_ADMIN, TEMPLATE_OWNER, TEMPLATE_EDITOR}
        result["can_manage_access"] = access_level in {TEMPLATE_ADMIN, TEMPLATE_OWNER}
    return result


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
    if objective == "OUTCOME_APP_PROMOTION":
        raise HTTPException(status_code=400, detail="当前系统暂不支持 App Promotion，请改用知名度、流量、互动、潜在客户或销售目标")
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
    targeting_errors = targeting_preflight_errors("模板定向", targeting)
    if targeting_errors:
        raise HTTPException(status_code=400, detail=targeting_errors[0]["message"])
    geo_locations = targeting.get("geo_locations") or {}
    if not any(geo_locations.get(field) for field in ("countries", "regions", "cities", "zips", "custom_locations")):
        raise HTTPException(status_code=400, detail="定向必须至少选择一个国家、地区、城市、邮编或自定义位置")
    if targeting.get("age_min") is not None and targeting.get("age_max") is not None and int(targeting["age_min"]) > int(targeting["age_max"]):
        raise HTTPException(status_code=400, detail="年龄范围无效：最小年龄不能大于最大年龄")

    config = values.get("creative_config_json") or {}
    if budget_type == "LIFETIME" and not (config.get("schedule") or {}).get("end_time"):
        raise HTTPException(status_code=400, detail="总预算模板必须配置 schedule.end_time")
    objective = str(values.get("objective") or "OUTCOME_TRAFFIC").upper()
    optimization_goal = str(values.get("optimization_goal") or default_optimization_goal(objective)).upper()
    # Pixel / Dataset 只属于实际使用网站转化优化的模板或广告组；保存时即清理
    # 非转化目标的残留字段，避免旧模板在后续发布时继续携带无关 promoted_object。
    config = filter_unused_tracking_assets(optimization_goal, config)
    values["creative_config_json"] = config
    objective_errors = objective_optimization_preflight_errors(objective, optimization_goal, config)
    if objective_errors:
        raise HTTPException(status_code=400, detail=objective_errors[0]["message"])
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
        targeting_errors = targeting_preflight_errors(f"广告组 {index} 定向", adset_targeting)
        if targeting_errors:
            raise HTTPException(status_code=400, detail=targeting_errors[0]["message"])
        adset_geo = adset_targeting.get("geo_locations") or {}
        if not any(adset_geo.get(field) for field in ("countries", "regions", "cities", "zips", "custom_locations")):
            raise HTTPException(status_code=400, detail=f"广告组 {index} 至少配置一个国家、地区、城市、邮编或自定义位置")
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
        placement_errors = placement_preflight_errors(f"广告组 {index} 版位", adset_placements)
        if placement_errors:
            raise HTTPException(status_code=400, detail=placement_errors[0]["message"])
        for key in ("publisher_platforms", "facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions"):
            if adset_placements.get(key) is not None and not isinstance(adset_placements.get(key), list):
                raise HTTPException(status_code=400, detail=f"广告组 {index} 的版位字段 {key} 必须是数组")
        # 广告组级事件源同样在发布预检阶段校验，模板保存不拦截。
    try:
        creative_format = normalize_creative_format(config.get("creative_format"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Persist the canonical value when this config is passed through create/update.
    config["creative_format"] = creative_format
    # Keep the stored shape mode-specific. Older templates used ``creatives``
    # for carousel cards; migrate that shape on create/update so downstream
    # publish code never has to interpret two competing lists.
    if creative_format == "CAROUSEL":
        cards = config.get("carousel_cards")
        if not isinstance(cards, list) or not cards:
            cards = config.get("creatives") if isinstance(config.get("creatives"), list) else []
        config["carousel_cards"] = cards
        config.pop("creatives", None)
        if isinstance(config.get("adsets"), list):
            config["adsets"] = [
                {key: value for key, value in item.items() if key != "creatives"}
                if isinstance(item, dict) else item
                for item in config["adsets"]
            ]
    else:
        config.pop("carousel_cards", None)
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
        try:
            normalized_cta = normalize_cta(creative.get("cta"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"创意 {index}：{exc}") from exc
        if normalized_cta:
            creative["cta"] = normalized_cta


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


class TemplateCollaboratorRequest(BaseModel):
    role: str = Field("VIEWER", description="EDITOR 或 VIEWER")

    @validator("role")
    def normalize_role(cls, value):
        normalized = str(value or "").upper()
        if normalized not in {TEMPLATE_EDITOR, TEMPLATE_VIEWER}:
            raise ValueError("模板协作角色只能是 EDITOR 或 VIEWER")
        return normalized


# ==================== 路由 ====================

@router.get("")
def list_templates(
    status: Optional[str] = Query("ACTIVE", description="按状态过滤 ACTIVE / DISABLED / ARCHIVED；默认仅返回 ACTIVE"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """模板列表"""
    query = template_query(db.query(CampaignTemplate), current_user).filter(CampaignTemplate.is_temporary.is_(False))
    # 删除采用软删除（ARCHIVED）以保留历史投放映射；普通模板页只展示可用模板。
    # 对显式传入空字符串也回退到 ACTIVE，避免归档记录意外泄漏到默认列表。
    selected_status = (status or TemplateStatus.ACTIVE.value).upper()
    query = query.filter(CampaignTemplate.status == selected_status)
    items = query.order_by(CampaignTemplate.created_at.desc()).all()
    return [_template_response(t, db, current_user) for t in items]


@router.post("", status_code=201)
def create_template(
    req: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建投放模板"""
    # ARCHIVED 模板保留用于历史投放映射，不应继续占用新模板名称。
    # 同一租户内只禁止与当前 ACTIVE 模板重名。
    if owned_query(db.query(CampaignTemplate), CampaignTemplate, current_user).filter(
        CampaignTemplate.name == req.name,
        CampaignTemplate.status == TemplateStatus.ACTIVE.value,
    ).first():
        raise HTTPException(status_code=400, detail=f"模板名称已存在: {req.name}")

    payload = req.dict(exclude_none=False)
    creative_config = dict(payload.get("creative_config_json") or {})
    try:
        creative_config["creative_format"] = normalize_creative_format(creative_config.get("creative_format"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["creative_config_json"] = creative_config
    _validate_page_for_tenant(db, creative_config)
    _validate_delivery_config(payload)
    template = CampaignTemplate(
        id=uuid.uuid4().hex,
        tenant_id=tenant_required(current_user),
        created_by=getattr(current_user, "id", None),
        **payload,
        status=TemplateStatus.ACTIVE.value,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_response(template, db, current_user)


def _get_template_for_access(db: Session, template_id: str, current_user: User) -> CampaignTemplate:
    template = template_query(db.query(CampaignTemplate), current_user).filter(
        CampaignTemplate.id == template_id,
        CampaignTemplate.is_temporary.is_(False),
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在或无权访问")
    return template


@router.get("/{template_id}/collaborator-candidates")
def list_template_collaborator_candidates(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """列出当前租户可被模板所有者授权的成员。"""
    template = _get_template_for_access(db, template_id, current_user)
    if not can_manage_template_access(db, template, current_user):
        raise HTTPException(status_code=403, detail="只有模板所有者或管理员可以管理协作成员")
    tenant_id = tenant_required(current_user)
    users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.is_active.is_(True),
        User.id != template.created_by,
    ).order_by(User.username.asc()).all()
    return [
        {"id": user.id, "username": user.username, "email": user.email}
        for user in users
    ]


@router.get("/{template_id}/collaborators")
def list_template_collaborators(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    template = _get_template_for_access(db, template_id, current_user)
    if not can_manage_template_access(db, template, current_user):
        raise HTTPException(status_code=403, detail="只有模板所有者或管理员可以查看协作成员")
    rows = db.query(TemplateCollaborator).filter(
        TemplateCollaborator.tenant_id == tenant_required(current_user),
        TemplateCollaborator.template_id == template.id,
        TemplateCollaborator.status == "ACTIVE",
    ).order_by(TemplateCollaborator.created_at.asc()).all()
    return [row.to_dict() for row in rows]


@router.put("/{template_id}/collaborators/{user_id}")
def upsert_template_collaborator(
    template_id: str,
    user_id: str,
    req: TemplateCollaboratorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    template = _get_template_for_access(db, template_id, current_user)
    if not can_manage_template_access(db, template, current_user):
        raise HTTPException(status_code=403, detail="只有模板所有者或管理员可以管理协作成员")
    if user_id == template.created_by:
        raise HTTPException(status_code=400, detail="模板所有者无需添加为协作成员")
    tenant_id = tenant_required(current_user)
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant_id,
        User.is_active.is_(True),
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="租户成员不存在或已停用")
    row = db.query(TemplateCollaborator).filter(
        TemplateCollaborator.tenant_id == tenant_id,
        TemplateCollaborator.template_id == template.id,
        TemplateCollaborator.user_id == user_id,
    ).first()
    if row:
        row.role = req.role
        row.status = "ACTIVE"
        row.granted_by = current_user.id
    else:
        row = TemplateCollaborator(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            template_id=template.id,
            user_id=user_id,
            role=req.role,
            status="ACTIVE",
            granted_by=current_user.id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.delete("/{template_id}/collaborators/{user_id}")
def remove_template_collaborator(
    template_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    template = _get_template_for_access(db, template_id, current_user)
    if not can_manage_template_access(db, template, current_user):
        raise HTTPException(status_code=403, detail="只有模板所有者或管理员可以管理协作成员")
    row = db.query(TemplateCollaborator).filter(
        TemplateCollaborator.tenant_id == tenant_required(current_user),
        TemplateCollaborator.template_id == template.id,
        TemplateCollaborator.user_id == user_id,
    ).first()
    if row:
        row.status = "REVOKED"
        db.commit()
    return {"status": "ok"}


@router.get("/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """模板详情"""
    template = _get_template_for_access(db, template_id, current_user)
    return _template_response(template, db, current_user)


@router.patch("/{template_id}")
def update_template(
    template_id: str,
    req: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新模板（仅更新传入字段）"""
    template = _get_template_for_access(db, template_id, current_user)
    if not can_edit_template(db, template, current_user):
        raise HTTPException(status_code=403, detail="没有编辑该模板的权限")

    values = req.dict(exclude_unset=True)
    if "creative_config_json" in values:
        creative_config = dict(values.get("creative_config_json") or {})
        try:
            creative_config["creative_format"] = normalize_creative_format(creative_config.get("creative_format"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        values["creative_config_json"] = creative_config
    merged = template.to_dict()
    merged.update(values)
    _validate_delivery_config(merged)
    if "creative_config_json" in values:
        values["creative_config_json"] = merged["creative_config_json"]
        _validate_page_for_tenant(db, values["creative_config_json"])
    elif merged["creative_config_json"] != template.creative_config_json:
        # 顺手清理历史模板的残留事件源，但不因一次名称/状态更新重新触发
        # Facebook Page 校验，避免无关更新被失效页面阻断。
        values["creative_config_json"] = merged["creative_config_json"]
    for field, value in values.items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return _template_response(template, db, current_user)


@router.post("/{template_id}/clone", status_code=201)
def clone_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """复制模板（设计文档第 37.3 节）"""
    source = _get_template_for_access(db, template_id, current_user)

    clone = CampaignTemplate(
        id=uuid.uuid4().hex,
        tenant_id=tenant_required(current_user),
        created_by=getattr(current_user, "id", None),
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
        creative_config_json=filter_unused_tracking_assets(
            source.optimization_goal or default_optimization_goal(source.objective),
            source.creative_config_json,
        ),
        status=TemplateStatus.ACTIVE.value,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _template_response(clone, db, current_user)


@router.delete("/{template_id}")
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """删除模板（软删除：置为 ARCHIVED，保留历史实例映射）"""
    template = _get_template_for_access(db, template_id, current_user)
    if not can_manage_template_access(db, template, current_user):
        raise HTTPException(status_code=403, detail="只有模板所有者或管理员可以删除模板")

    template.status = TemplateStatus.ARCHIVED.value
    db.commit()
    return {"id": template_id, "status": template.status}
