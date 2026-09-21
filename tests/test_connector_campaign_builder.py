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

    payload = build_connector_payload(
        template,
        "act_1",
        asset_bindings={"asset-1": "video-1"},
        asset_thumbnail_hashes={"asset-1": "cover-1"},
    )
    creative = payload["adsets"][0]["creatives"][0]
    assert creative["object_story_spec"]["video_data"]["video_id"] == "video-1"
    assert creative["object_story_spec"]["video_data"]["image_hash"] == "cover-1"


def test_build_connector_payload_uses_binding_asset_type_when_template_omits_it():
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
                "primary_text": "hello",
                "landing_url": "https://example.com",
            }],
        },
    )

    try:
        build_connector_payload(
            template,
            "act_1",
            asset_bindings={"asset-1": "video-1"},
            asset_types={"asset-1": "video"},
        )
    except ValueError as exc:
        assert "缩略图" in str(exc)
    else:
        raise AssertionError("缺少视频缩略图时应阻止创建广告创意")


def test_build_connector_payload_copies_adset_config_without_reusing_meta_ids():
    template = SimpleNamespace(
        name="Target Campaign",
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

    payload = build_connector_payload(
        template,
        "act_target",
        copy_ad_group={
            "name": "Source AdSet",
            "targeting": {"geo_locations": {"countries": ["CA"]}},
            "daily_budget": 2500,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        },
    )

    assert "existing_id" not in payload["campaign"]
    assert "existing_id" not in payload["adsets"][0]
    assert payload["adsets"][0]["name"] == "Source AdSet Copy"
    assert payload["adsets"][0]["daily_budget"] == 2500
    assert payload["adsets"][0]["targeting"]["geo_locations"]["countries"] == ["CA"]


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
