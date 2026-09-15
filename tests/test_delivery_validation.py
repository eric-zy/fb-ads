import pytest
from fastapi import HTTPException

from api.templates import _validate_delivery_config


def _values(**creative_overrides):
    creative = {
        "asset_type": "image",
        "asset_id": "asset-1",
        "image_hash": "hash-1",
        "landing_url": "https://example.com/landing",
    }
    creative.update(creative_overrides.pop("creative", {}))
    config = {
        "page_id": "page-1",
        "creatives": [creative],
        "delivery": {"split_level": "AD", "combination_mode": "ACCOUNT_X_ADSET_X_CREATIVE"},
    }
    config.update(creative_overrides.pop("creative_config_json", {}))
    values = {
        "objective": "OUTCOME_TRAFFIC",
        "optimization_goal": "LINK_CLICKS",
        "billing_event": "IMPRESSIONS",
        "daily_budget": 10,
        "targeting_json": {"geo_locations": {"countries": ["US"]}},
        "creative_config_json": config,
    }
    values.update(creative_overrides)
    return values


def test_sales_rejects_link_clicks():
    with pytest.raises(HTTPException) as exc:
        _validate_delivery_config(_values(objective="OUTCOME_SALES"))
    assert "OUTCOME_SALES" in exc.value.detail


def test_adset_split_is_allowed():
    values = _values()
    values["creative_config_json"]["delivery"]["split_level"] = "ADSET"
    _validate_delivery_config(values)


def test_campaign_split_is_rejected_until_supported():
    values = _values()
    values["creative_config_json"]["delivery"]["split_level"] = "CAMPAIGN"
    with pytest.raises(HTTPException) as exc:
        _validate_delivery_config(values)
    assert "CAMPAIGN" in exc.value.detail


def test_carousel_requires_ad_split():
    values = _values()
    values["creative_config_json"].update({
        "creative_format": "CAROUSEL",
        "carousel_cards": [
            {"asset_type": "image", "asset_id": "a1", "image_hash": "h1"},
            {"asset_type": "image", "asset_id": "a2", "image_hash": "h2"},
        ],
    })
    values["creative_config_json"]["delivery"]["split_level"] = "ADSET"
    with pytest.raises(HTTPException) as exc:
        _validate_delivery_config(values)
    assert "轮播广告" in exc.value.detail


def test_unknown_combination_mode_is_rejected():
    values = _values()
    values["creative_config_json"]["delivery"]["combination_mode"] = "ACCOUNT_X_CREATIVE"
    with pytest.raises(HTTPException) as exc:
        _validate_delivery_config(values)
    assert "组合方式" in exc.value.detail
