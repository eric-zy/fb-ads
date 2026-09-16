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


def build_connector_payload(template: Any, meta_account_id: str, *, budget_override: float | None = None,
                            status: str = "PAUSED", campaign_name: str | None = None,
                            adset_name: str | None = None) -> dict[str, Any]:
    service = _PayloadService()
    campaign = CampaignBuilder(service, template, meta_account_id, status=status, campaign_name=campaign_name).build_params()
    creative_config = copy.deepcopy(template.creative_config_json or {})
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
            creative = CreativeBuilder(service, meta_account_id, cfg,
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
