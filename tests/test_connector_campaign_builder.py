from types import SimpleNamespace

from api.templates import _validate_delivery_config
from services.connector_campaign_builder import build_connector_payload


def test_build_connector_payload_contains_complete_tree():
    template = SimpleNamespace(
        name="Demo",
        objective="TRAFFIC",
        special_ad_categories=[],
        is_adset_budget_sharing_enabled=False,
        buying_type="AUCTION",
        budget_type="DAILY",
        daily_budget=10,
        lifetime_budget=None,
        billing_event="IMPRESSIONS",
        optimization_goal="LINK_CLICKS",
        targeting_json={"geo_locations": {"countries": ["US"]}},
        placement_json={},
        bid_strategy=None,
        creative_config_json={
            "page_id": "page-1",
            "creatives": [{
                "page_id": "page-1",
                "asset_type": "image",
                "image_hash": "hash-1",
                "message": "hello",
                "landing_url": "https://example.com",
            }],
        },
    )

    payload = build_connector_payload(template, "act_1")
    assert payload["campaign"]["objective"] == "OUTCOME_TRAFFIC"
    assert payload["adsets"][0]["client_key"] == "adset-1"
    creative = payload["adsets"][0]["creatives"][0]
    assert creative["client_key"] == "creative-1-1"
    assert creative["ads"][0]["client_key"] == "ad-1-1"
    assert creative["ads"][0]["adset_id"] == "${adset.id}"
    assert payload["adsets"][0]["daily_budget"] == 1000


def test_build_connector_payload_resolves_account_scoped_video_binding():
    template = SimpleNamespace(
        name="Video Demo",
        objective="TRAFFIC",
        special_ad_categories=[],
        is_adset_budget_sharing_enabled=False,
        buying_type="AUCTION",
        budget_type="DAILY",
        daily_budget=10,
        lifetime_budget=None,
        billing_event="IMPRESSIONS",
        optimization_goal="LINK_CLICKS",
        targeting_json={"geo_locations": {"countries": ["US"]}},
        placement_json={},
        bid_strategy=None,
        creative_config_json={
            "page_id": "page-1",
            "creatives": [{
                "asset_id": "asset-1",
                "asset_type": "video",
                "primary_text": "hello",
                "landing_url": "https://example.com",
            }],
        },
    )

    payload = build_connector_payload(template, "act_1", asset_bindings={"asset-1": "video-1"})
    creative = payload["adsets"][0]["creatives"][0]
    assert creative["object_story_spec"]["video_data"]["video_id"] == "video-1"


def test_template_validation_accepts_video_asset_id_before_account_sync():
    _validate_delivery_config({
        "objective": "OUTCOME_TRAFFIC",
        "buying_type": "AUCTION",
        "budget_type": "DAILY",
        "daily_budget": 10,
        "targeting_json": {"geo_locations": {"countries": ["US"]}},
        "creative_config_json": {
            "creatives": [{"asset_type": "video", "asset_id": "asset-1"}],
        },
    })
