"""Carousel buttons are per-card choices, independent from landing URLs."""
import copy

import pytest
from fastapi import HTTPException
from api.jobs import CampaignCreateRequest, _ensure_template
from api.templates import _validate_delivery_config
from models import CampaignTemplate
from services.campaign_builder import CreativeBuilder
from services.connector_campaign_builder import build_connector_payload


def config(mode="CUSTOM", selected=(4,)):
    return {
        "page_id": "page-1", "creative_format": "CAROUSEL", "carousel_cta_mode": mode,
        "shared_creative": {"primary_text": "Carousel story", "cta": "LEARN_MORE"},
        "carousel_cards": [
            {"asset_id": f"asset-{i}", "asset_type": "image", "image_hash": f"hash-{i}",
             "headline": f"Card {i}", "landing_url": f"https://example.com/{i}",
             "show_cta": i in selected} for i in range(5)
        ],
    }


@pytest.mark.parametrize("mode,selected,expected", [
    ("CUSTOM", (4,), [4]), ("CUSTOM", (0, 2, 4), [0, 2, 4]),
    ("CUSTOM", (), []), ("ALL", (4,), [0, 1, 2, 3, 4]),
])
def test_buttons_select_last_arbitrary_none_or_all_without_global_inheritance(mode, selected, expected):
    cfg = config(mode, selected)
    original = copy.deepcopy(cfg)
    data = CreativeBuilder(None, "act_1", cfg).build_params()["object_story_spec"]["link_data"]
    assert [i for i, card in enumerate(data["child_attachments"]) if "call_to_action" in card] == expected
    for i in expected:
        assert data["child_attachments"][i]["call_to_action"]["value"]["link"] == f"https://example.com/{i}"
    assert len(data["child_attachments"]) == 5
    assert all(card["link"] for card in data["child_attachments"])
    assert cfg == original
    if mode == "CUSTOM":
        assert "call_to_action" not in data
        assert data["multi_share_optimized"] is data["multi_share_end_card"] is False


def test_individual_button_type_and_no_button_are_not_overwritten_by_shared_cta():
    cfg = config("ALL")
    cfg["carousel_cards"][0]["cta"] = "SHOP_NOW"
    cfg["carousel_cards"][1]["cta"] = "NO_BUTTON"
    data = CreativeBuilder(None, "act_1", cfg).build_params()["object_story_spec"]["link_data"]
    assert data["child_attachments"][0]["call_to_action"]["type"] == "SHOP_NOW"
    assert "call_to_action" not in data["child_attachments"][1]
    assert "call_to_action" not in data


def test_direct_snapshot_and_connector_keep_custom_buttons(db):
    inline = {**config(), "name": "Carousel", "objective": "OUTCOME_TRAFFIC", "daily_budget": 10,
        "optimization_goal": "LINK_CLICKS", "adsets": [{"name": "US", "budget": 10,
            "targeting": {"geo_locations": {"countries": ["US"]}}, "optimization_goal": "LINK_CLICKS"}]}
    request = CampaignCreateRequest(source="DIRECT", inline_config=inline, ad_account_ids=["account-1"])
    template = db.get(CampaignTemplate, _ensure_template(db, request, "test_tenant"))
    assert template.creative_config_json["carousel_cta_mode"] == "CUSTOM"
    assert template.creative_config_json["shared_creative"]["cta"] == "LEARN_MORE"
    payload = build_connector_payload(template, "act_1")
    cards = payload["adsets"][0]["creatives"][0]["object_story_spec"]["link_data"]["child_attachments"]
    assert [i for i, card in enumerate(cards) if "call_to_action" in card] == [4]


@pytest.mark.parametrize("invalid", [{"carousel_cta_mode": "LAST"}, {"carousel_cards": [{"show_cta": "false"}]}])
def test_template_rejects_invalid_selection_instead_of_enabling_all(invalid):
    cfg = {**config(), **invalid}
    values = {"objective": "OUTCOME_TRAFFIC", "daily_budget": 10, "budget_type": "DAILY",
              "targeting_json": {"geo_locations": {"countries": ["US"]}}, "creative_config_json": cfg}
    with pytest.raises(HTTPException) as error:
        _validate_delivery_config(values)
    assert error.value.status_code == 400
