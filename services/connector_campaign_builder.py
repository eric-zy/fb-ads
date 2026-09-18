"""将现有 CampaignTemplate 转换为 Connector 投放协议 payload。

此模块只构造参数，不访问数据库外的 Meta API，也不读取 Access Token。
"""
from __future__ import annotations

import copy
from typing import Any

from services.campaign_builder import CampaignBuilder, AdSetBuilder, CreativeBuilder


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


def _resolve_asset_refs(config: dict[str, Any], asset_bindings: dict[str, str]) -> dict[str, Any]:
    """把素材库 asset_id 解析为当前广告账户的 Meta 素材 ID。

    素材绑定是按广告账户保存的，不能把某个账户的 video_id/image_hash
    固化到共享模板或 CreativeAsset 上。模板保存时可以只有 asset_id，
    投放时由调用方传入当前账户的 READY 绑定。
    """
    resolved = copy.deepcopy(config or {})

    def resolve_one(item: dict[str, Any]) -> None:
        asset_id = item.get("asset_id")
        meta_asset_id = asset_bindings.get(str(asset_id)) if asset_id else None
        if not meta_asset_id:
            return
        if str(item.get("asset_type") or "image").lower() == "video":
            item["video_id"] = meta_asset_id
        else:
            item["image_hash"] = meta_asset_id

    resolve_one(resolved)
    for card in resolved.get("carousel_cards") or []:
        if isinstance(card, dict):
            resolve_one(card)
    return resolved


def build_connector_payload(template: Any, meta_account_id: str, *, budget_override: float | None = None,
                            status: str = "PAUSED", campaign_name: str | None = None,
                            adset_name: str | None = None,
                            asset_bindings: dict[str, str] | None = None) -> dict[str, Any]:
    service = _PayloadService()
    campaign = CampaignBuilder(service, template, meta_account_id, status=status, campaign_name=campaign_name).build_params()
    asset_bindings = {str(key): str(value) for key, value in (asset_bindings or {}).items() if value}
    creative_config = _resolve_asset_refs(template.creative_config_json or {}, asset_bindings)
    delivery = creative_config.get("delivery") or {}
    adset_configs = creative_config.get("adsets") or [{}]
    logical = []
    for config in adset_configs:
        creatives = config.get("creatives") or creative_config.get("creatives") or [creative_config]
        if creative_config.get("creative_format") == "CAROUSEL":
            creatives = [creative_config]
        logical.append((config, creatives))

    adsets = []
    for index, (config, creatives) in enumerate(logical, 1):
        adset = AdSetBuilder(service, template, meta_account_id, "${campaign.id}", budget_override=budget_override,
                             status=status, adset_name=adset_name, adset_config=config).build_params()
        adset["client_key"] = f"adset-{index}"
        adset["creatives"] = []
        for cindex, cfg in enumerate(creatives, 1):
            resolved_cfg = _resolve_asset_refs(cfg, asset_bindings)
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
