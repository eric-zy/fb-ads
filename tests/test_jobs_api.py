"""Job API 直接投放配置的契约回归测试。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.jobs import CampaignCreateRequest, _ensure_template
from core.enums import ActionType
from models import AdAccount, CampaignTemplate
from services import job_service
from services.job_service import JobService


def _direct_request(**overrides):
    config = {
        "name": "Direct Dataset Campaign",
        "objective": "OUTCOME_SALES",
        "daily_budget": 20,
        "page_id": "page-1",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "dataset_id": "dataset-1",
        "conversion_event": "PURCHASE",
        "adsets": [{
            "name": "AdSet 1",
            "budget": 20,
            "targeting": {"geo_locations": {"countries": ["US"]}},
            "placement": {"publisher_platforms": ["facebook"]},
            "optimization_goal": "OFFSITE_CONVERSIONS",
        }],
        "creatives": [{
            "asset_id": "asset-1",
            "primary_text": "Hello",
            "landing_url": "https://example.com",
        }],
    }
    config.update(overrides)
    return CampaignCreateRequest(
        inline_config=config,
        ad_account_ids=["account-1"],
        source="DIRECT",
    )


def test_ensure_template_forwards_top_level_dataset_and_event(db):
    template_id = _ensure_template(db, _direct_request(), "test_tenant")

    template = db.get(CampaignTemplate, template_id)
    assert template.creative_config_json["dataset_id"] == "dataset-1"
    assert template.creative_config_json["conversion_event"] == "PURCHASE"
    assert template.is_temporary is True


def test_ensure_template_normalizes_legacy_creative_format(db):
    template_id = _ensure_template(db, _direct_request(creative_format="MULTI_AD"), "test_tenant")

    template = db.get(CampaignTemplate, template_id)
    assert template.creative_config_json["creative_format"] == "SINGLE_IMAGE_VIDEO"


def test_ensure_template_rejects_invalid_conversion_event(db):
    request = _direct_request(conversion_event="purchase-event")

    with pytest.raises(HTTPException) as exc_info:
        _ensure_template(db, request, "test_tenant")

    assert exc_info.value.status_code == 400
    assert "转化事件" in str(exc_info.value.detail)


def test_ensure_template_preserves_carousel_cards_and_rejects_single_card(db):
    card = {
        "asset_id": "asset-1",
        "asset_type": "image",
        "primary_text": "Hello",
        "landing_url": "https://example.com",
    }
    request = _direct_request(
        creative_format="CAROUSEL",
        carousel_cards=[card],
    )

    with pytest.raises(HTTPException) as exc_info:
        _ensure_template(db, request, "test_tenant")

    assert exc_info.value.status_code == 400
    assert "2-10" in str(exc_info.value.detail)

    request = _direct_request(
        creative_format="CAROUSEL",
        carousel_cards=[card, {**card, "asset_id": "asset-2"}],
    )
    template_id = _ensure_template(db, request, "test_tenant")
    template = db.get(CampaignTemplate, template_id)
    assert len(template.creative_config_json["carousel_cards"]) == 2
    assert "creatives" not in template.creative_config_json


def test_ensure_template_migrates_legacy_carousel_creatives(db):
    card = {
        "asset_id": "asset-1",
        "asset_type": "image",
        "primary_text": "Hello",
        "landing_url": "https://example.com",
    }
    request = _direct_request(
        creative_format="CAROUSEL",
        creatives=[card, {**card, "asset_id": "asset-2"}],
    )

    template_id = _ensure_template(db, request, "test_tenant")
    template = db.get(CampaignTemplate, template_id)
    assert [item["asset_id"] for item in template.creative_config_json["carousel_cards"]] == ["asset-1", "asset-2"]
    assert "creatives" not in template.creative_config_json


def test_ensure_template_allows_carousel_without_primary_text(db):
    card = {
        "asset_id": "asset-1",
        "asset_type": "image",
        "landing_url": "https://example.com/1",
    }
    request = _direct_request(
        creative_format="CAROUSEL",
        carousel_cards=[card, {**card, "asset_id": "asset-2", "landing_url": "https://example.com/2"}],
    )

    template_id = _ensure_template(db, request, "test_tenant")
    template = db.get(CampaignTemplate, template_id)
    assert [item["asset_id"] for item in template.creative_config_json["carousel_cards"]] == ["asset-1", "asset-2"]


def test_ensure_template_allows_video_without_landing_url(db):
    request = _direct_request(
        objective="OUTCOME_ENGAGEMENT",
        optimization_goal="THRUPLAY",
        adsets=[{
            "name": "AdSet 1",
            "budget": 20,
            "targeting": {"geo_locations": {"countries": ["US"]}},
            "placement": {"publisher_platforms": ["facebook"]},
            "optimization_goal": "THRUPLAY",
        }],
        creatives=[{
            "asset_id": "video-1",
            "asset_type": "video",
            "primary_text": "Video creative",
            "cta": "NO_BUTTON",
        }],
    )

    template_id = _ensure_template(db, request, "test_tenant")
    template = db.get(CampaignTemplate, template_id)
    assert template.creative_config_json["creatives"][0]["asset_type"] == "video"
    assert "landing_url" not in template.creative_config_json["creatives"][0]


def test_existing_campaign_action_does_not_require_page(monkeypatch, db):
    """启停已有 Campaign 不应复用新建投放的 Page 校验。"""
    template = CampaignTemplate(
        id="template-without-page",
        tenant_id="test_tenant",
        name="Legacy template",
        creative_config_json={},
    )
    account = AdAccount(
        id="action-account",
        tenant_id="test_tenant",
        account_id="act_action",
        account_name="Action account",
        connector_credential_id="connector-credential",
        account_status="1",
        system_status="ACTIVE",
    )
    db.add_all([template, account])
    db.commit()

    monkeypatch.setattr(
        "services.meta.AdAccountService.filter_available_ids",
        lambda self, ids, **kwargs: (list(ids), []),
    )
    monkeypatch.setattr(
        job_service,
        "execute_campaign_job",
        SimpleNamespace(delay=lambda job_id: SimpleNamespace(id="celery-action-task")),
    )

    job = JobService(db).create_job(
        template_id=template.id,
        ad_account_ids=[account.id],
        action_type=ActionType.ENABLE,
    )

    assert job.action_type == ActionType.ENABLE.value
    assert job.total_accounts == 1
