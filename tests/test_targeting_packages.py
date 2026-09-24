"""地区组与定向包接口的回归测试。"""

import pytest
from fastapi import HTTPException

from api.targeting_packages import (
    RegionGroupRequest,
    TargetingPackageRequest,
    create_region_group,
    create_targeting_package,
    delete_region_group,
    delete_targeting_package,
    list_region_groups,
    list_targeting_packages,
    update_targeting_package,
)
from models import AdAccount


class _AdminUser:
    id = "targeting-test-user"

    def is_admin(self):
        return True


class _ViewerUser:
    id = "targeting-test-viewer"

    def is_admin(self):
        return False


@pytest.fixture
def ad_account(db):
    account = AdAccount(id="targeting-account", account_id="act_targeting")
    db.add(account)
    db.commit()
    return account


def _region_request(**overrides):
    payload = {
        "name": "美国地区组",
        "geo_locations": {"countries": ["US", "US"], "location_types": ["home", "home"]},
        "excluded_geo_locations": {"countries": ["CA"]},
        "account_ids": ["targeting-account"],
        "description": "投放测试",
    }
    payload.update(overrides)
    return RegionGroupRequest(**payload)


def _package_request(**overrides):
    payload = {
        "name": "美国流量定向",
        "targeting_json": {
            "geo_locations": {"countries": ["US", "US"], "location_types": ["home", "home"]},
            "age_min": 18,
            "age_max": 65,
            "genders": [1, 2],
            "custom_audiences": [{"id": "aud-1", "ad_account_id": "act_targeting"}],
        },
        "placement_json": {"publisher_platforms": ["facebook"]},
        "account_ids": ["targeting-account"],
        "region_group_ids": [],
    }
    payload.update(overrides)
    return TargetingPackageRequest(**payload)


def test_region_group_crud_normalizes_geo_and_archives(db, ad_account):
    user = _AdminUser()
    created = create_region_group(_region_request(), db, user)

    assert created["geo_locations"]["countries"] == ["US"]
    assert created["geo_locations"]["location_types"] == ["home"]
    assert created["account_ids"] == [ad_account.id]
    assert len(list_region_groups("ACTIVE", db, user)) == 1

    delete_region_group(created["id"], db, user)
    assert list_region_groups("ACTIVE", db, user) == []
    assert len(list_region_groups("ARCHIVED", db, user)) == 1


def test_targeting_package_crud_normalizes_targeting_and_archives(db, ad_account):
    user = _AdminUser()
    region = create_region_group(_region_request(), db, user)
    request = _package_request(region_group_ids=[region["id"]])
    created = create_targeting_package(request, db, user)

    targeting = created["targeting_json"]
    assert targeting["geo_locations"]["countries"] == ["US"]
    assert targeting["geo_locations"]["location_types"] == ["home"]
    assert created["region_group_ids"] == [region["id"]]

    request.targeting_json["age_min"] = 21
    updated = update_targeting_package(created["id"], request, db, user)
    assert updated["targeting_json"]["age_min"] == 21

    delete_targeting_package(created["id"], db, user)
    assert list_targeting_packages("ACTIVE", db, user) == []
    assert len(list_targeting_packages("ARCHIVED", db, user)) == 1


def test_targeting_rejects_included_and_excluded_country_conflict(db, ad_account):
    with pytest.raises(HTTPException) as exc_info:
        create_region_group(
            _region_request(excluded_geo_locations={"countries": ["US"]}),
            db,
            _AdminUser(),
        )

    assert exc_info.value.status_code == 400
    assert "重复" in str(exc_info.value.detail)


def test_targeting_rejects_account_without_access(db, ad_account):
    with pytest.raises(HTTPException) as exc_info:
        create_region_group(_region_request(), db, _ViewerUser())

    assert exc_info.value.status_code == 403
    assert "无权" in str(exc_info.value.detail)
