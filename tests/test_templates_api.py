"""Template API contract tests for mode-specific creative persistence."""

import pytest
from fastapi import HTTPException

from api.templates import TemplateCreate, TemplateUpdate, create_template, update_template
from models import CampaignTemplate, MetaPage


def _template_values(**creative_config):
    return {
        "name": "Carousel contract template",
        "objective": "OUTCOME_TRAFFIC",
        "budget_type": "DAILY",
        "daily_budget": 10,
        "targeting_json": {"geo_locations": {"countries": ["US"]}},
        "creative_config_json": {
            "page_id": "page-1",
            **creative_config,
        },
    }


def _seed_page(db):
    db.add(MetaPage(
        id="page-row-1",
        page_id="page-1",
        page_name="Test Page",
        credential_id="credential-1",
        status="ACTIVE",
    ))
    db.commit()


def test_create_template_persists_carousel_cards_without_duplicate_creatives(db):
    _seed_page(db)
    request = TemplateCreate(**_template_values(
        creative_format="CAROUSEL",
        creatives=[
            {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            {"asset_type": "image", "asset_id": "asset-2", "landing_url": "https://example.com/2"},
        ],
    ))

    result = create_template(request, db, None)

    config = result["creative_config_json"]
    assert [card["asset_id"] for card in config["carousel_cards"]] == ["asset-1", "asset-2"]
    assert "creatives" not in config


def test_update_template_migrates_legacy_carousel_shape(db):
    _seed_page(db)
    create_request = TemplateCreate(**_template_values(
        creative_format="CAROUSEL",
        carousel_cards=[
            {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            {"asset_type": "image", "asset_id": "asset-2", "landing_url": "https://example.com/2"},
        ],
    ))
    created = create_template(create_request, db, None)

    # Simulate a pre-migration row that still has the old duplicate field.
    template = db.get(CampaignTemplate, created["id"])
    template.creative_config_json = {
        **template.creative_config_json,
        "creatives": template.creative_config_json["carousel_cards"],
    }
    template.creative_config_json.pop("carousel_cards", None)
    db.commit()

    update_request = TemplateUpdate(creative_config_json=template.creative_config_json)
    result = update_template(created["id"], update_request, db, None)

    config = result["creative_config_json"]
    assert [card["asset_id"] for card in config["carousel_cards"]] == ["asset-1", "asset-2"]
    assert "creatives" not in config


def test_create_template_persists_adset_targeting_and_scoped_audiences(db):
    _seed_page(db)
    request = TemplateCreate(**_template_values(
        creatives=[
            {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
        ],
        adsets=[
            {
                "name": "US mobile",
                "budget": 20,
                "targeting": {
                    "geo_locations": {"countries": ["US"], "location_types": ["home", "recent"]},
                    "excluded_geo_locations": {"countries": ["CA"]},
                    "age_min": 18,
                    "age_max": 55,
                    "genders": [1, 2],
                    "custom_audiences": [{"id": "aud-in", "ad_account_id": "act-1"}],
                    "excluded_custom_audiences": [{"id": "aud-out", "ad_account_id": "act-1"}],
                    "device_platforms": ["mobile"],
                    "user_os": ["iOS"],
                    "user_device": ["iPhone"],
                    "wireless_carrier": ["wifi"],
                    "targeting_automation": {"advantage_audience": 1},
                },
                "placement": {"publisher_platforms": ["facebook"], "facebook_positions": ["feed"]},
            },
        ],
    ))

    result = create_template(request, db, None)

    adset = result["creative_config_json"]["adsets"][0]
    targeting = adset["targeting"]
    assert targeting["excluded_geo_locations"] == {"countries": ["CA"]}
    assert targeting["custom_audiences"] == [{"id": "aud-in", "ad_account_id": "act-1"}]
    assert targeting["excluded_custom_audiences"] == [{"id": "aud-out", "ad_account_id": "act-1"}]
    assert targeting["device_platforms"] == ["mobile"]
    assert targeting["user_os"] == ["iOS"]
    assert targeting["user_device"] == ["iPhone"]
    assert targeting["wireless_carrier"] == ["wifi"]


def test_create_template_rejects_overlapping_adset_audiences(db):
    _seed_page(db)
    request = TemplateCreate(**_template_values(
        creatives=[
            {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
        ],
        adsets=[
            {
                "name": "US",
                "budget": 20,
                "targeting": {
                    "geo_locations": {"countries": ["US"]},
                    "custom_audiences": [{"id": "aud-same", "ad_account_id": "act-1"}],
                    "excluded_custom_audiences": [{"id": "aud-same", "ad_account_id": "act-1"}],
                },
                "placement": {},
            },
        ],
    ))

    with pytest.raises(HTTPException) as exc_info:
        create_template(request, db, None)
    assert exc_info.value.status_code == 400
    assert "aud-same" in exc_info.value.detail


def test_create_template_accepts_region_only_adset_geo(db):
    _seed_page(db)
    request = TemplateCreate(**_template_values(
        creatives=[
            {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
        ],
        adsets=[
            {
                "name": "California",
                "budget": 20,
                "targeting": {"geo_locations": {"regions": [{"key": "3847"}]}},
                "placement": {},
            },
        ],
    ))

    result = create_template(request, db, None)

    assert result["creative_config_json"]["adsets"][0]["targeting"]["geo_locations"]["regions"] == [{"key": "3847"}]
