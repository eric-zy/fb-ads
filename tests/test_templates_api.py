"""Template API contract tests for mode-specific creative persistence."""

import pytest
from fastapi import HTTPException

from api.templates import TemplateCreate, TemplateUpdate, create_template, delete_template, list_templates, update_template
from models import CampaignTemplate, MetaPage, TemplateCollaborator, User


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


def _user(user_id="test001", role="user"):
    return User(
        id=user_id,
        email=f"{user_id}@test.local",
        username=user_id,
        hashed_password="not-used",
        tenant_id="test_tenant",
        role=role,
        is_active=True,
    )


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


def test_non_admin_can_update_template_they_created(db):
    _seed_page(db)
    user = _user()
    db.add(user)
    db.commit()

    created = create_template(
        TemplateCreate(**_template_values(
            creatives=[
                {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            ],
        )),
        db,
        user,
    )

    updated = update_template(
        created["id"],
        TemplateUpdate(name="Updated by test001"),
        db,
        user,
    )

    assert updated["name"] == "Updated by test001"
    assert updated["created_by"] == "test001"


def test_non_admin_cannot_update_another_users_template(db):
    _seed_page(db)
    owner = _user("owner")
    other_user = _user("test001")
    db.add_all([owner, other_user])
    db.commit()

    created = create_template(
        TemplateCreate(**_template_values(
            creatives=[
                {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            ],
        )),
        db,
        owner,
    )

    with pytest.raises(HTTPException) as exc_info:
        update_template(created["id"], TemplateUpdate(name="Should fail"), db, other_user)

    assert exc_info.value.status_code == 404


def test_template_editor_can_update_shared_template(db):
    _seed_page(db)
    owner = _user("owner")
    editor = _user("test001")
    db.add_all([owner, editor])
    db.commit()

    created = create_template(
        TemplateCreate(**_template_values(
            creatives=[
                {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            ],
        )),
        db,
        owner,
    )
    db.add(TemplateCollaborator(
        id="share-editor-1",
        tenant_id="test_tenant",
        template_id=created["id"],
        user_id=editor.id,
        role="EDITOR",
        status="ACTIVE",
        granted_by=owner.id,
    ))
    db.commit()

    updated = update_template(
        created["id"],
        TemplateUpdate(name="Updated by shared editor"),
        db,
        editor,
    )

    assert updated["name"] == "Updated by shared editor"
    assert updated["access_level"] == "EDITOR"
    assert updated["can_edit"] is True


def test_template_viewer_cannot_update_shared_template(db):
    _seed_page(db)
    owner = _user("owner")
    viewer = _user("viewer")
    db.add_all([owner, viewer])
    db.commit()

    created = create_template(
        TemplateCreate(**_template_values(
            creatives=[
                {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            ],
        )),
        db,
        owner,
    )
    db.add(TemplateCollaborator(
        id="share-viewer-1",
        tenant_id="test_tenant",
        template_id=created["id"],
        user_id=viewer.id,
        role="VIEWER",
        status="ACTIVE",
        granted_by=owner.id,
    ))
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        update_template(created["id"], TemplateUpdate(name="Should fail"), db, viewer)

    assert exc_info.value.status_code == 403


def test_archived_template_is_hidden_from_default_list_but_available_explicitly(db):
    _seed_page(db)
    owner = _user("owner")
    db.add(owner)
    db.commit()

    created = create_template(
        TemplateCreate(**_template_values(
            creatives=[
                {"asset_type": "image", "asset_id": "asset-1", "landing_url": "https://example.com/1"},
            ],
        )),
        db,
        owner,
    )
    deleted = delete_template(created["id"], db, owner)

    assert deleted["status"] == "ARCHIVED"
    assert list_templates(None, db, owner) == []
    archived = list_templates("ARCHIVED", db, owner)
    assert [item["id"] for item in archived] == [created["id"]]
