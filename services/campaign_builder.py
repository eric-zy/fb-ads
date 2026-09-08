"""Campaign Builder（设计文档第 21 节）

设计文档要求将 Campaign / AdSet / Creative / Ad 的创建逻辑拆开：

    CampaignBuilder
          ├── AdSetBuilder
          ├── CreativeBuilder
          └── AdBuilder

并向"部署"语义对齐：

    Template ──部署到──> Account A
                             ├── Campaign（1 个）
                             │      └── AdSet（N 个）
                             │             └── Ad（N 个）

注意：这与原有 AdsManager.publish_batch 的语义完全不同 ——
原实现按「账户 × 素材 × 文案」做笛卡尔积，每个组合都创建一个 Campaign，
100 账户 × 3 素材 × 2 文案 会产生 600 个 Campaign，
既不符合设计文档的模板部署模型，也无法聚合管理。
"""
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from core.enums import InstanceStatus
from core.logger import logger
from models import (
    AdInstance,
    AdSetInstance,
    CampaignInstance,
    CampaignTemplate,
)
from services.meta.service import MetaAdsService


def _new_id() -> str:
    return uuid.uuid4().hex


def _usd_to_cents(amount: Optional[float]) -> Optional[int]:
    """Meta 金额以「分」为单位"""
    if amount is None:
        return None
    return int(round(float(amount) * 100))


# Meta 的 ODAX 目标值。旧模板可能仍保存旧版目标名，部署前统一转换，
# 避免把系统内部/旧版枚举直接发给 Graph API。
_OBJECTIVE_ALIASES = {
    "CONVERSIONS": "OUTCOME_SALES",
    "LINK_CLICKS": "OUTCOME_TRAFFIC",
    "TRAFFIC": "OUTCOME_TRAFFIC",
    "REACH": "OUTCOME_AWARENESS",
    "BRAND_AWARENESS": "OUTCOME_AWARENESS",
    "VIDEO_VIEWS": "OUTCOME_ENGAGEMENT",
    "ENGAGEMENT": "OUTCOME_ENGAGEMENT",
    "LEAD_GENERATION": "OUTCOME_LEADS",
}
_VALID_OBJECTIVES = {
    "OUTCOME_AWARENESS", "OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_APP_PROMOTION",
}


class CampaignBuilder:
    """构建并创建 Campaign

    注意：meta_ad_account_id 是 Meta 侧的广告账户 ID（如 act_123 / 123），
    与系统内部主键 ad_accounts.id 不是同一个东西，勿混用。
    """

    def __init__(
        self,
        service: MetaAdsService,
        template: CampaignTemplate,
        meta_ad_account_id: str,
        *,
        status: str = InstanceStatus.PAUSED.value,
        name_suffix: str = "",
        campaign_name: Optional[str] = None,
    ):
        self.service = service
        self.template = template
        self.meta_ad_account_id = meta_ad_account_id
        self.status = status
        self.name_suffix = name_suffix
        self.campaign_name = campaign_name

    def build_params(self) -> Dict[str, Any]:
        name = self.campaign_name or f"{self.template.name}{self.name_suffix}"
        raw_objective = (self.template.objective or "").strip().upper()
        objective = _OBJECTIVE_ALIASES.get(raw_objective, raw_objective)
        if objective not in _VALID_OBJECTIVES:
            raise ValueError(
                f"模板推广目标无效：{self.template.objective!r}。"
                f"请使用 {', '.join(sorted(_VALID_OBJECTIVES))}"
            )
        params: Dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": self.status,
            "special_ad_categories": self.template.special_ad_categories or [],
        }
        # AUCTION 是 Meta 默认值；不主动发送可减少不同账户/版本的参数兼容问题。
        buying_type = (self.template.buying_type or "AUCTION").strip().upper()
        if buying_type and buying_type != "AUCTION":
            params["buying_type"] = buying_type
        return params

    def build(self) -> Dict[str, Any]:
        return self.service.create_campaign(self.meta_ad_account_id, self.build_params())


class AdSetBuilder:
    """构建并创建 AdSet"""

    def __init__(
        self,
        service: MetaAdsService,
        template: CampaignTemplate,
        meta_ad_account_id: str,
        campaign_id: str,
        *,
        budget_override: Optional[float] = None,
        status: str = InstanceStatus.PAUSED.value,
        name_suffix: str = "",
        adset_name: Optional[str] = None,
    ):
        self.service = service
        self.template = template
        self.meta_ad_account_id = meta_ad_account_id
        self.campaign_id = campaign_id
        self.budget_override = budget_override
        self.status = status
        self.name_suffix = name_suffix
        self.adset_name = adset_name

    def _resolve_budget_cents(self) -> Optional[int]:
        """预算优先级：Job 覆盖值 > 模板日预算 > 模板总预算"""
        if self.budget_override is not None:
            return _usd_to_cents(self.budget_override)
        if self.template.budget_type == "LIFETIME":
            return _usd_to_cents(self.template.lifetime_budget)
        return _usd_to_cents(self.template.daily_budget)

    def build_params(self) -> Dict[str, Any]:
        budget_cents = self._resolve_budget_cents()
        if not budget_cents or budget_cents <= 0:
            raise ValueError("广告组预算必须大于 0")

        targeting = dict(self.template.targeting_json or {"geo_locations": {"countries": ["US"]}})
        # Meta 将 publisher_platforms/facebook_positions 等版位字段放在 targeting 中。
        targeting.update(self.template.placement_json or {})
        params: Dict[str, Any] = {
            "name": self.adset_name or f"{self.template.name}{self.name_suffix} AdSet",
            "campaign_id": self.campaign_id,
            "status": self.status,
            "billing_event": self.template.billing_event or "IMPRESSIONS",
            "optimization_goal": self.template.optimization_goal or "LINK_CLICKS",
            # 定向来自模板 JSONB，避免硬编码（原实现硬编码 US + reach）
            "targeting": targeting,
        }

        if self.template.budget_type == "LIFETIME":
            schedule = (self.template.creative_config_json or {}).get("schedule") or {}
            end_time = schedule.get("end_time")
            if not end_time:
                raise ValueError("总预算投放必须配置 schedule.end_time")
            params["lifetime_budget"] = budget_cents
            params["end_time"] = end_time
            if schedule.get("start_time"):
                params["start_time"] = schedule["start_time"]
        else:
            params["daily_budget"] = budget_cents

        optimization_goal = str(params["optimization_goal"]).upper()
        if optimization_goal in {"OFFSITE_CONVERSIONS", "VALUE"}:
            promoted_object = (self.template.creative_config_json or {}).get("promoted_object")
            if not promoted_object:
                raise ValueError(
                    f"优化目标 {optimization_goal} 必须配置 creative_config_json.promoted_object"
                )
            params["promoted_object"] = promoted_object

        if self.template.bid_strategy:
            bid_strategy = self.template.bid_strategy.upper()
            params["bid_strategy"] = bid_strategy
            bidding = (self.template.creative_config_json or {}).get("bidding") or {}
            if bid_strategy in {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"}:
                if not bidding.get("bid_amount"):
                    raise ValueError(f"出价策略 {bid_strategy} 必须配置 bidding.bid_amount")
                params["bid_amount"] = int(bidding["bid_amount"])
            if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS":
                if not bidding.get("bid_constraints"):
                    raise ValueError("最低 ROAS 出价必须配置 bidding.bid_constraints")
                params["bid_constraints"] = bidding["bid_constraints"]
        return params

    def build(self) -> Dict[str, Any]:
        return self.service.create_adset(self.meta_ad_account_id, self.build_params())


class CreativeBuilder:
    """构建并创建 AdCreative"""

    def __init__(
        self,
        service: MetaAdsService,
        meta_ad_account_id: str,
        creative_config: Dict[str, Any],
        page_id: Optional[str] = None,
        *,
        name: str = "Creative",
    ):
        self.service = service
        self.meta_ad_account_id = meta_ad_account_id
        self.creative_config = creative_config or {}
        self.page_id = page_id or self.creative_config.get("page_id")
        self.name = name

    def build_params(self) -> Dict[str, Any]:
        if not self.page_id:
            raise ValueError("广告创意缺少 Facebook Page ID，请在模板中选择已同步页面")
        cfg = self.creative_config
        asset_type = cfg.get("asset_type", "image")

        # 按素材类型组装 object_story_spec（原实现将 page_id 硬编码为空串，导致创建必失败）
        if asset_type == "video":
            if not cfg.get("video_id"):
                raise ValueError("视频创意缺少已上传到目标广告账户的 video_id")
            media_data: Dict[str, Any] = {
                "video_id": cfg.get("video_id"),
                "title": cfg.get("headline", ""),
                "message": cfg.get("primary_text", ""),
            }
            if cfg.get("landing_url"):
                media_data["call_to_action"] = {
                    "type": cfg.get("cta", "LEARN_MORE"),
                    "value": {"link": cfg["landing_url"]},
                }
            story_key = "video_data"
        else:
            if not cfg.get("image_hash"):
                raise ValueError("图片创意缺少已上传到目标广告账户的 image_hash")
            if not cfg.get("landing_url"):
                raise ValueError("图片链接广告缺少 landing_url")
            media_data = {
                "image_hash": cfg.get("image_hash"),
                "message": cfg.get("primary_text", ""),
                "link": cfg["landing_url"],
            }
            if cfg.get("headline"):
                media_data["name"] = cfg["headline"]
            if cfg.get("description"):
                media_data["description"] = cfg["description"]
            if cfg.get("cta"):
                media_data["call_to_action"] = {
                    "type": cfg["cta"],
                    "value": {"link": cfg.get("landing_url", "")},
                }
            # 带落地页、标题和 CTA 的图片广告属于 link_data；photo_data
            # 不接受 message/name/description/call_to_action 这些字段。
            story_key = "link_data"

        object_story_spec = {
            "page_id": self.page_id,
            story_key: media_data,
        }

        return {
            "name": f"{self.name} Creative",
            "object_story_spec": object_story_spec,
        }

    def build(self) -> Dict[str, Any]:
        return self.service.create_creative(self.meta_ad_account_id, self.build_params())


class AdBuilder:
    """构建并创建 Ad"""

    def __init__(
        self,
        service: MetaAdsService,
        meta_ad_account_id: str,
        adset_id: str,
        creative_id: str,
        *,
        name: str = "Ad",
        status: str = InstanceStatus.PAUSED.value,
        campaign_name: Optional[str] = None,
        adset_name: Optional[str] = None,
    ):
        self.service = service
        self.meta_ad_account_id = meta_ad_account_id
        self.adset_id = adset_id
        self.creative_id = creative_id
        self.name = name
        self.status = status

    def build_params(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "adset_id": self.adset_id,
            "creative": {"creative_id": self.creative_id},
            "status": self.status,
        }

    def build(self) -> Dict[str, Any]:
        return self.service.create_ad(self.meta_ad_account_id, self.build_params())


class CampaignDeploymentBuilder:
    """把「一个模板」部署到「一个广告账户」，并落库实例映射

    产出结构：1 Campaign → 1 AdSet → N Ad（N = 创意数量）
    同时写入 campaign_instances / adset_instances / ad_instances
    （设计文档第 12 / 13 / 14 节）
    """

    def __init__(
        self,
        db: Session,
        service: MetaAdsService,
        template: CampaignTemplate,
        ad_account_id: str,
        meta_ad_account_id: str,
        *,
        budget_override: Optional[float] = None,
        status: str = InstanceStatus.PAUSED.value,
    ):
        self.db = db
        self.service = service
        self.template = template
        # ad_account_id      → 系统内部主键，用于实例表外键
        # meta_ad_account_id → Meta 侧账户 ID（act_xxx / 数字），用于 API 调用
        self.ad_account_id = ad_account_id
        self.meta_ad_account_id = meta_ad_account_id
        self.budget_override = budget_override
        self.status = status
        self.campaign_name = campaign_name
        self.adset_name = adset_name
        self.created_meta_ids: List[str] = []

    def _cleanup_created(self) -> List[str]:
        """逆序删除本次已创建的 Meta 对象，返回未能清理的对象 ID。"""
        failed: List[str] = []
        for object_id in reversed(self.created_meta_ids):
            try:
                self.service.delete_object(object_id)
            except Exception as exc:
                failed.append(object_id)
                logger.error(f"[Deployment] 补偿删除失败 object={object_id}: {exc}")
        return failed

    def find_existing(self) -> Optional[CampaignInstance]:
        """幂等查询：同一模板在同一账户是否已部署（设计文档第 29 节）"""
        return (
            self.db.query(CampaignInstance)
            .filter(
                CampaignInstance.template_id == self.template.id,
                CampaignInstance.ad_account_id == self.ad_account_id,
            )
            .first()
        )

    def build(self) -> Dict[str, Any]:
        """执行部署，返回结果摘要"""
        # ---- 幂等：已部署则直接返回，避免重复创建 ----
        existing = self.find_existing()
        if existing:
            logger.info(
                f"[Deployment] 模板 {self.template.id} 已部署到账户 {self.ad_account_id}，跳过"
            )
            return {
                "skipped": True,
                "campaign_instance_id": existing.id,
                "meta_campaign_id": existing.meta_campaign_id,
                "adset_ids": [a.meta_adset_id for a in existing.adsets],
                "ad_ids": [
                    ad.meta_ad_id for a in existing.adsets for ad in a.ads
                ],
            }

        try:
            return self._build()
        except Exception as exc:
            self.db.rollback()
            failed_cleanup = self._cleanup_created()
            if failed_cleanup:
                logger.error(f"[Deployment] 需要人工清理 Meta 对象: {failed_cleanup}")
                setattr(exc, "cleanup_failed_ids", failed_cleanup)
            raise

    def _build(self) -> Dict[str, Any]:
        meta_account_id = self.meta_ad_account_id

        # ---- 1. Campaign ----
        campaign = CampaignBuilder(
            self.service, self.template, meta_account_id, status=self.status, campaign_name=self.campaign_name
        ).build()
        self.created_meta_ids.append(campaign["id"])
        campaign_instance = CampaignInstance(
            id=_new_id(),
            template_id=self.template.id,
            ad_account_id=self.ad_account_id,
            meta_campaign_id=campaign["id"],
            name=self.template.name,
            status=self.status,
        )
        self.db.add(campaign_instance)
        self.db.flush()

        # ---- 2. AdSet ----
        adset = AdSetBuilder(
            self.service,
            self.template,
            meta_account_id,
            campaign["id"],
            budget_override=self.budget_override,
            status=self.status,
            adset_name=self.adset_name,
        ).build()
        self.created_meta_ids.append(adset["id"])
        adset_instance = AdSetInstance(
            id=_new_id(),
            campaign_instance_id=campaign_instance.id,
            meta_adset_id=adset["id"],
            name=f"{self.template.name} AdSet",
            status=self.status,
        )
        self.db.add(adset_instance)
        self.db.flush()

        # ---- 3. Creative + Ad（每个创意配置生成一个 Ad） ----
        creative_config = self.template.creative_config_json or {}
        creatives = creative_config.get("creatives")
        if not creatives:
            # 兼容：模板未拆分多创意时，整体作为一个创意配置
            creatives = [creative_config] if creative_config else [{}]

        ad_ids: List[str] = []
        for idx, cfg in enumerate(creatives, 1):
            creative = CreativeBuilder(
                self.service,
                meta_account_id,
                cfg,
                page_id=creative_config.get("page_id"),
                name=f"{self.template.name} C{idx}",
            ).build()
            self.created_meta_ids.append(creative["id"])

            ad = AdBuilder(
                self.service,
                meta_account_id,
                adset["id"],
                creative["id"],
                name=f"{self.template.name} A{idx}",
                status=self.status,
            ).build()
            self.created_meta_ids.append(ad["id"])

            self.db.add(
                AdInstance(
                    id=_new_id(),
                    adset_instance_id=adset_instance.id,
                    creative_id=cfg.get("asset_id"),
                    meta_ad_id=ad["id"],
                    name=f"{self.template.name} A{idx}",
                    status=self.status,
                )
            )
            ad_ids.append(ad["id"])

        self.db.commit()

        return {
            "skipped": False,
            "campaign_instance_id": campaign_instance.id,
            "meta_campaign_id": campaign["id"],
            "adset_ids": [adset["id"]],
            "ad_ids": ad_ids,
        }
