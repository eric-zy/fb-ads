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

注意：这里是当前 Connector 投放协议的构建器 ——
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
from services.meta_audience_policy import resolve_required_exclusions
from services.targeting_catalog import normalize_targeting
from services.meta_delivery_rules import default_optimization_goal, is_pixel_required
from services.meta_creative_options import normalize_cta


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
            "is_adset_budget_sharing_enabled": bool(self.template.is_adset_budget_sharing_enabled),
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
        adset_config: Optional[Dict[str, Any]] = None,
    ):
        self.service = service
        self.template = template
        self.meta_ad_account_id = meta_ad_account_id
        self.campaign_id = campaign_id
        self.budget_override = budget_override
        self.status = status
        self.name_suffix = name_suffix
        self.adset_name = adset_name
        self.adset_config = adset_config or {}

    def _resolve_budget_cents(self) -> Optional[int]:
        """预算优先级：Job 覆盖值 > 模板日预算 > 模板总预算"""
        if self.budget_override is not None:
            return _usd_to_cents(self.budget_override)
        if self.adset_config.get("budget") is not None:
            return _usd_to_cents(self.adset_config["budget"])
        if self.template.budget_type == "LIFETIME":
            return _usd_to_cents(self.template.lifetime_budget)
        return _usd_to_cents(self.template.daily_budget)

    def build_params(self) -> Dict[str, Any]:
        budget_cents = self._resolve_budget_cents()
        if not budget_cents or budget_cents <= 0:
            raise ValueError("广告组预算必须大于 0")

        targeting = normalize_targeting(
            dict(self.adset_config.get("targeting") or self.template.targeting_json or {"geo_locations": {"countries": ["US"]}})
        )
        # XMP/Meta 多账户批量创建的关键约束：受众引用必须属于当前目标账户。
        # 未解析的旧模板引用交给发布预检处理，这里只拒绝明确错配，避免把
        # 一个账户的 Audience ID 静默发到另一个账户。
        for field in ("custom_audiences", "excluded_custom_audiences", "excluded_audiences"):
            for audience in targeting.get(field) or []:
                scoped_account = str(audience.get("ad_account_id") or audience.get("account_id") or "").strip()
                if scoped_account and scoped_account.replace("act_", "") != str(self.meta_ad_account_id).replace("act_", ""):
                    raise ValueError(
                        f"定向字段 {field} 的受众 {audience.get('id')} 不属于目标广告账户 {self.meta_ad_account_id}"
                    )
        # Meta 将 publisher_platforms/facebook_positions 等版位字段放在 targeting 中。
        targeting.update(self.adset_config.get("placement") or self.template.placement_json or {})
        # Meta 新版 AdSet 要求明确声明 Advantage+ 受众开关；旧模板默认启用，显式 0 仍保留。
        automation = targeting.get("targeting_automation")
        if not isinstance(automation, dict):
            targeting["targeting_automation"] = {"advantage_audience": 1}
        elif automation.get("advantage_audience") not in (0, 1):
            raise ValueError("targeting_automation.advantage_audience 必须是 0 或 1")
        params: Dict[str, Any] = {
            "name": self.adset_name or self.adset_config.get("name") or f"{self.template.name}{self.name_suffix} AdSet",
            "campaign_id": self.campaign_id,
            "status": self.status,
            "billing_event": self.adset_config.get("billing_event") or self.template.billing_event or "IMPRESSIONS",
            "optimization_goal": self.adset_config.get("optimization_goal") or self.template.optimization_goal or default_optimization_goal(self.template.objective),
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
        objective = str(self.template.objective or "OUTCOME_TRAFFIC").upper()
        if objective == "OUTCOME_SALES" and optimization_goal in {"LINK_CLICKS", "LANDING_PAGE_VIEWS"}:
            raise ValueError("OUTCOME_SALES 不支持 LINK_CLICKS/LANDING_PAGE_VIEWS；请改用 OUTCOME_TRAFFIC，或配置 OFFSITE_CONVERSIONS 及 promoted_object")
        if is_pixel_required(optimization_goal):
            config = {**(self.template.creative_config_json or {}), **self.adset_config}
            promoted_object = config.get("promoted_object")
            if not promoted_object:
                dataset_id = config.get("dataset_id")
                pixel_id = config.get("pixel_id")
                event = str(config.get("conversion_event") or config.get("custom_event_type") or "").strip()
                if dataset_id and event:
                    promoted_object = {"dataset_id": dataset_id, "conversion_event": event}
                elif pixel_id and event:
                    promoted_object = {"pixel_id": pixel_id, "custom_event_type": event}
            if not promoted_object:
                raise ValueError(
                    f"优化目标 {optimization_goal} 必须配置 creative_config_json.promoted_object"
                )
            params["promoted_object"] = promoted_object

        if self.adset_config.get("bid_strategy") or self.template.bid_strategy:
            bid_strategy = (self.adset_config.get("bid_strategy") or self.template.bid_strategy).upper()
            params["bid_strategy"] = bid_strategy
            bidding = {**((self.template.creative_config_json or {}).get("bidding") or {}), **({"bid_amount": self.adset_config.get("bid_amount")} if self.adset_config.get("bid_amount") is not None else {})}
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

        if cfg.get("creative_format") == "CAROUSEL":
            cards = cfg.get("carousel_cards") or []
            if not 2 <= len(cards) <= 10:
                raise ValueError("轮播广告需要 2-10 张图片卡片")
            child_attachments = []
            for index, card in enumerate(cards, 1):
                if card.get("asset_type", "image") != "image" or not card.get("image_hash"):
                    raise ValueError(f"轮播第 {index} 张卡片缺少已上传图片")
                if not card.get("landing_url"):
                    raise ValueError(f"轮播第 {index} 张卡片缺少 landing_url")
                child = {"image_hash": card["image_hash"], "link": card["landing_url"]}
                if card.get("headline"): child["name"] = card["headline"]
                if card.get("description"): child["description"] = card["description"]
                child_attachments.append(child)
            media_data = {
                "message": cfg.get("primary_text", ""),
                "link": cards[0]["landing_url"],
                "child_attachments": child_attachments,
            }
            cta = normalize_cta(cfg.get("cta"))
            if cta and cta != "NO_BUTTON":
                media_data["call_to_action"] = {"type": cta, "value": {"link": cards[0]["landing_url"]}}
            story_key = "link_data"
        else:
            story_key = None

        # 按素材类型组装 object_story_spec（原实现将 page_id 硬编码为空串，导致创建必失败）
        if story_key == "link_data":
            pass
        elif asset_type == "video":
            if not cfg.get("video_id"):
                raise ValueError("视频创意缺少已上传到目标广告账户的 video_id")
            thumbnail_hash = cfg.get("thumbnail_hash") or cfg.get("image_hash")
            if not thumbnail_hash and not cfg.get("thumbnail_url"):
                raise ValueError("视频创意缺少 Meta 缩略图，请先完成视频封面同步")
            media_data: Dict[str, Any] = {
                "video_id": cfg.get("video_id"),
                "title": cfg.get("headline", ""),
                "message": cfg.get("primary_text", ""),
            }
            if thumbnail_hash:
                media_data["image_hash"] = thumbnail_hash
            elif cfg.get("thumbnail_url"):
                media_data["image_url"] = cfg["thumbnail_url"]
            if cfg.get("description"):
                media_data["link_description"] = cfg["description"]
            cta = normalize_cta(cfg.get("cta"))
            if cfg.get("landing_url") and cta != "NO_BUTTON":
                media_data["call_to_action"] = {
                    "type": cta or "LEARN_MORE",
                    "value": {
                        "link": cfg["landing_url"],
                        **({"link_caption": cfg["display_link"]} if cfg.get("display_link") else {}),
                    },
                }
            if cfg.get("url_tags"):
                media_data["url_tags"] = cfg["url_tags"]
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
            cta = normalize_cta(cfg.get("cta"))
            if cta and cta != "NO_BUTTON":
                media_data["call_to_action"] = {
                    "type": cta,
                    "value": {"link": cfg.get("landing_url", "")},
                }
            if cfg.get("display_link"):
                media_data["caption"] = cfg["display_link"]
            if cfg.get("url_tags"):
                media_data["url_tags"] = cfg["url_tags"]
            # 带落地页、标题和 CTA 的图片广告属于 link_data；photo_data
            # 不接受 message/name/description/call_to_action 这些字段。
            story_key = "link_data"

        object_story_spec = {
            "page_id": self.page_id,
            story_key: media_data,
        }
        if self.creative_config.get("instagram_actor_id"):
            object_story_spec["instagram_actor_id"] = self.creative_config["instagram_actor_id"]

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
        campaign_name: Optional[str] = None,
        adset_name: Optional[str] = None,
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
                logger.info(f"[Deployment] 补偿清理成功 object={object_id}")
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
            setattr(exc, "cleanup_attempted_ids", list(reversed(self.created_meta_ids)))
            setattr(exc, "cleanup_failed_ids", failed_cleanup)
            if failed_cleanup:
                logger.error(f"[Deployment] 需要人工清理 Meta 对象: {failed_cleanup}")
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

        creative_config = self.template.creative_config_json or {}
        delivery = creative_config.get("delivery") or {}
        split_level = str(delivery.get("split_level") or "AD").upper()
        combination_mode = str(delivery.get("combination_mode") or "ACCOUNT_X_ADSET_X_CREATIVE").upper()
        if combination_mode != "ACCOUNT_X_ADSET_X_CREATIVE":
            raise ValueError("当前仅支持账户 × 广告组 × 素材组合方式")
        if split_level not in {"AD", "ADSET"}:
            raise ValueError("当前支持按 AD 或 ADSET 拆分；按 CAMPAIGN 拆分将在后续版本开放")
        adset_configs = creative_config.get("adsets") or [{}]
        required_exclusions = resolve_required_exclusions(self.db, self.ad_account_id)["snapshot"][
            "required_excluded_audience_ids"
        ]
        if required_exclusions:
            # 账户级合规策略在部署快照阶段合并，保证 direct Meta 模式与
            # Connector 模式行为一致；模板原始 JSON 不被修改。
            resolved_configs = []
            for raw_config in adset_configs:
                config = dict(raw_config or {})
                targeting = dict(config.get("targeting") or self.template.targeting_json or {})
                existing = list(targeting.get("excluded_custom_audiences") or [])
                existing_ids = {str(item.get("id") if isinstance(item, dict) else item) for item in existing}
                for audience_id in required_exclusions:
                    if str(audience_id) not in existing_ids:
                        existing.append({"id": str(audience_id), "resolution": "POLICY"})
                targeting["excluded_custom_audiences"] = existing
                config["targeting"] = targeting
                resolved_configs.append(config)
            adset_configs = resolved_configs
        all_adset_ids: List[str] = []
        ad_ids: List[str] = []
        logical_adsets = []
        for adset_config in adset_configs:
            creatives = adset_config.get("creatives") or creative_config.get("creatives")
            if creative_config.get("creative_format") == "CAROUSEL":
                creatives = [creative_config]
            if not creatives:
                creatives = [creative_config] if creative_config else [{}]
            if split_level == "ADSET" and creative_config.get("creative_format") != "CAROUSEL":
                for creative in creatives:
                    logical_adsets.append((adset_config, [creative]))
            else:
                logical_adsets.append((adset_config, creatives))

        for adset_idx, (adset_config, creatives) in enumerate(logical_adsets, 1):
            adset = AdSetBuilder(
                self.service,
                self.template,
                meta_account_id,
                campaign["id"],
                budget_override=self.budget_override,
                status=self.status,
                adset_name=self.adset_name,
                adset_config=adset_config,
            ).build()
            self.created_meta_ids.append(adset["id"])
            all_adset_ids.append(adset["id"])
            adset_instance = AdSetInstance(id=_new_id(), campaign_instance_id=campaign_instance.id, meta_adset_id=adset["id"], name=adset_config.get("name") or f"{self.template.name} AdSet {adset_idx}", status=self.status)
            self.db.add(adset_instance)
            self.db.flush()
            for idx, cfg in enumerate(creatives, 1):
                creative = CreativeBuilder(self.service, meta_account_id, cfg, page_id=adset_config.get("page_id") or creative_config.get("page_id"), name=f"{self.template.name} G{adset_idx} C{idx}").build()
                self.created_meta_ids.append(creative["id"])
                ad = AdBuilder(self.service, meta_account_id, adset["id"], creative["id"], name=f"{self.template.name} G{adset_idx} A{idx}", status=self.status).build()
                self.created_meta_ids.append(ad["id"])
                self.db.add(AdInstance(id=_new_id(), adset_instance_id=adset_instance.id, creative_id=cfg.get("asset_id"), meta_ad_id=ad["id"], name=f"{self.template.name} G{adset_idx} A{idx}", status=self.status))
                ad_ids.append(ad["id"])

        self.db.commit()

        return {
            "skipped": False,
            "campaign_instance_id": campaign_instance.id,
            "meta_campaign_id": campaign["id"],
            "adset_ids": all_adset_ids,
            "ad_ids": ad_ids,
        }
