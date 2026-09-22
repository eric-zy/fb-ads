"""将现有 CampaignTemplate 转换为 Connector 投放协议 payload。

此模块只构造参数，不访问数据库外的 Meta API，也不读取 Access Token。
"""
from __future__ import annotations

import copy
import json
from typing import Any

from services.campaign_builder import CampaignBuilder, AdSetBuilder, CreativeBuilder
from services.creative_format import normalize_creative_format


class _PayloadService:
    """让既有参数 Builder 在无 Meta 客户端时也能复用。"""

    def create_campaign(self, account_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"id": "${campaign.id}", **params}

    def create_adset(self, account_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"id": "${adset.id}", **params}

    def create_creative(self, account_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"id": "${creative.id}", **params}

    def create_ad(self, account_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"id": "${ad.id}", **params}


def _resolve_asset_refs(
    config: dict[str, Any],
    asset_bindings: dict[str, str],
    asset_types: dict[str, str] | None = None,
    asset_thumbnail_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把素材库 asset_id 解析为当前广告账户的 Meta 素材 ID。

    素材绑定是按广告账户保存的，不能把某个账户的 video_id/image_hash
    固化到共享模板或 CreativeAsset 上。模板保存时可以只有 asset_id，
    投放时由调用方传入当前账户的 READY 绑定。
    """
    resolved = copy.deepcopy(config or {})
    asset_types = {str(key): str(value).lower() for key, value in (asset_types or {}).items() if value}
    asset_thumbnail_hashes = {
        str(key): str(value) for key, value in (asset_thumbnail_hashes or {}).items() if value
    }

    def resolve_one(item: dict[str, Any]) -> None:
        asset_id = item.get("asset_id")
        meta_asset_id = asset_bindings.get(str(asset_id)) if asset_id else None
        asset_type = str(
            item.get("asset_type")
            or asset_types.get(str(asset_id))
            or ("video" if item.get("video_id") else "image")
        ).lower()
        if asset_type not in {"image", "video"}:
            raise ValueError(f"不支持的素材类型: {asset_type}")
        item["asset_type"] = asset_type
        if not meta_asset_id:
            return
        if asset_type == "video":
            item["video_id"] = meta_asset_id
            thumbnail_hash = asset_thumbnail_hashes.get(str(asset_id)) if asset_id else None
            if thumbnail_hash:
                item["thumbnail_hash"] = thumbnail_hash
            # 防止旧模板残留 image_hash，导致视频被组装成 link_data。
            item.pop("image_hash", None)
        else:
            item["image_hash"] = meta_asset_id
            item.pop("video_id", None)

    resolve_one(resolved)
    for card in resolved.get("carousel_cards") or []:
        if isinstance(card, dict):
            resolve_one(card)
    return resolved


def build_connector_payload(template: Any, meta_account_id: str, *, budget_override: float | None = None,
                            status: str = "PAUSED", campaign_name: str | None = None,
                            adset_name: str | None = None,
                            asset_bindings: dict[str, str] | None = None,
                            asset_types: dict[str, str] | None = None,
                            asset_thumbnail_hashes: dict[str, str] | None = None,
                            required_excluded_audience_ids: list[str] | None = None,
                            existing_campaign_id: str | None = None,
                            existing_ad_group_id: str | None = None,
                            copy_ad_group: dict[str, Any] | None = None) -> dict[str, Any]:
    service = _PayloadService()
    campaign = CampaignBuilder(service, template, meta_account_id, status=status, campaign_name=campaign_name).build_params()
    if existing_campaign_id:
        # Connector 会识别该标记并跳过 Campaign 创建；其余字段保留，
        # 便于协议审计和无复用模式使用同一套 payload 结构。
        campaign["existing_id"] = existing_campaign_id
    asset_bindings = {str(key): str(value) for key, value in (asset_bindings or {}).items() if value}
    asset_types = {str(key): str(value).lower() for key, value in (asset_types or {}).items() if value}
    creative_config = _resolve_asset_refs(
        template.creative_config_json or {},
        asset_bindings,
        asset_types,
        asset_thumbnail_hashes,
    )
    # Normalize legacy templates before the payload reaches the Connector.
    creative_config["creative_format"] = normalize_creative_format(creative_config.get("creative_format"))
    delivery = creative_config.get("delivery") or {}
    adset_configs = creative_config.get("adsets") or [{}]
    logical = []
    for config in adset_configs:
        creatives = config.get("creatives") or creative_config.get("creatives") or [creative_config]
        if creative_config.get("creative_format") == "CAROUSEL":
            creatives = [creative_config]
        logical.append((config, creatives))

    adsets = []
    if existing_ad_group_id:
        logical = logical[:1]
    for index, (config, creatives) in enumerate(logical, 1):
        if copy_ad_group and index == 1:
            # COPY 模式只复制可迁移的广告组配置，不携带源账户的 Meta ID。
            # budget_override 仍由 AdSetBuilder 优先处理，方便投手按目标账户调整预算。
            config = copy.deepcopy(config)
            source_name = str(copy_ad_group.get("name") or "").strip()
            if source_name:
                config["name"] = f"{source_name} Copy"
            source_targeting = copy_ad_group.get("targeting")
            if isinstance(source_targeting, str):
                try:
                    source_targeting = json.loads(source_targeting)
                except (TypeError, ValueError):
                    source_targeting = None
            if isinstance(source_targeting, dict):
                config["targeting"] = source_targeting
            if budget_override is None and copy_ad_group.get("daily_budget") is not None:
                config["budget"] = float(copy_ad_group["daily_budget"]) / 100
            if copy_ad_group.get("bid_strategy"):
                config["bid_strategy"] = copy_ad_group["bid_strategy"]
            if copy_ad_group.get("bid_amount") is not None:
                config["bid_amount"] = copy_ad_group["bid_amount"]
        if required_excluded_audience_ids:
            config = copy.deepcopy(config)
            targeting = dict(config.get("targeting") or template.targeting_json or {})
            existing = list(targeting.get("excluded_custom_audiences") or [])
            existing_ids = {str(item.get("id") if isinstance(item, dict) else item) for item in existing}
            for audience_id in required_excluded_audience_ids:
                if str(audience_id) not in existing_ids:
                    existing.append({"id": str(audience_id), "resolution": "POLICY"})
            targeting["excluded_custom_audiences"] = existing
            config["targeting"] = targeting
        adset = AdSetBuilder(service, template, meta_account_id, "${campaign.id}", budget_override=budget_override,
                             status=status, adset_name=adset_name, adset_config=config).build_params()
        adset["client_key"] = f"adset-{index}"
        if existing_ad_group_id and index == 1:
            adset["existing_id"] = existing_ad_group_id
        adset["creatives"] = []
        for cindex, cfg in enumerate(creatives, 1):
            resolved_cfg = _resolve_asset_refs(
                cfg,
                asset_bindings,
                asset_types,
                asset_thumbnail_hashes,
            )
            creative = CreativeBuilder(service, meta_account_id, resolved_cfg,
                                       page_id=config.get("page_id") or creative_config.get("page_id"),
                                       name=f"{template.name} G{index} C{cindex}").build_params()
            creative["client_key"] = f"creative-{index}-{cindex}"
            creative["ads"] = [{"client_key": f"ad-{index}-{cindex}",
                                "name": f"{template.name} G{index} A{cindex}",
                                "status": status,
                                "adset_id": "${adset.id}",
                                "creative": {"creative_id": "${creative.id}"}}]
            adset["creatives"].append(creative)
        adsets.append(adset)
    return {"campaign": campaign, "adsets": adsets, "delivery": delivery}
