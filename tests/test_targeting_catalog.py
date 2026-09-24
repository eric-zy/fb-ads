import pytest

from services.targeting_catalog import normalize_country_code, normalize_languages, normalize_targeting, placement_preflight_errors, targeting_preflight_errors, validate_audience_refs


def test_language_alias_expands_and_deduplicates():
    assert normalize_languages(["中文", "zh-TW", "English"]) == ["zh_CN", "zh_TW", "en"]


def test_unknown_language_is_rejected():
    with pytest.raises(ValueError, match="不支持的 Meta 语言"):
        normalize_languages(["自定义语言"])


def test_audience_reference_keeps_account_scope():
    result = validate_audience_refs([
        {"id": "123", "ad_account_id": "act_1"},
        {"id": "123", "ad_account_id": "act_1"},
    ], "excluded_custom_audiences")
    assert result == [{"id": "123", "ad_account_id": "act_1"}]


def test_targeting_normalization_preserves_other_fields():
    result = normalize_targeting({
        "geo_locations": {"countries": ["HK"]},
        "languages": ["英语"],
        "excluded_custom_audiences": [{"id": "987", "ad_account_id": "act_2"}],
    })
    assert result["geo_locations"] == {"countries": ["HK"]}
    assert result["languages"] == ["en"]
    assert result["excluded_custom_audiences"][0]["ad_account_id"] == "act_2"


def test_country_names_are_normalized_to_meta_codes():
    assert normalize_country_code("美国") == "US"
    assert normalize_country_code("加拿大") == "CA"
    assert normalize_country_code("英国") == "GB"
    assert normalize_targeting({
        "geo_locations": {"countries": ["美国", "ca", "英国"]},
        "excluded_geo_locations": {"countries": ["加拿大"]},
    })["geo_locations"]["countries"] == ["US", "CA", "GB"]


def test_targeting_preflight_accepts_country_names_but_rejects_unknown_values():
    assert targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": ["美国", "加拿大", "英国"]},
    }) == []
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": ["不存在的国家"]},
    })
    assert {item["code"] for item in errors} == {"TARGETING_COUNTRY_CODE_INVALID"}


def test_geo_reference_objects_are_reduced_to_meta_keys():
    result = normalize_targeting({
        "geo_locations": {
            "regions": [{"id": "3847", "name": "Alberta", "search_type": "adgeolocation"}],
            "cities": [{"key": "2420600", "name": "Toronto"}],
            "zips": ["US:10001"],
        },
    })
    assert result["geo_locations"] == {
        "regions": [{"key": "3847"}],
        "cities": [{"key": "2420600"}],
        "zips": [{"key": "US:10001"}],
    }


def test_geo_reference_display_names_are_rejected():
    with pytest.raises(ValueError, match="稳定 key"):
        normalize_targeting({"geo_locations": {"regions": ["Alberta"]}})
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"cities": ["Toronto"]},
        "excluded_geo_locations": {"regions": ["Alberta"]},
    })
    assert {item["code"] for item in errors} == {"TARGETING_GEO_KEY_INVALID"}


def test_interest_refs_require_meta_id_and_are_normalized():
    result = normalize_targeting({
        "flexible_spec": [{
            "interests": [{"id": 6001, "name": "Movies", "search_type": "adinterest"}],
        }],
    })
    assert result["flexible_spec"] == [{"interests": [{"id": "6001", "name": "Movies"}]}]

    with pytest.raises(ValueError, match="兴趣必须从 Meta 兴趣目录选择"):
        normalize_targeting({"flexible_spec": [{"interests": [{"name": "Movies"}]}]})
    errors = targeting_preflight_errors("广告组 1 定向", {
        "flexible_spec": [{"interests": [{"name": "Movies"}]}],
    })
    assert {item["code"] for item in errors} == {"TARGETING_INTEREST_INVALID"}


def test_meta_targeting_resolves_product_language_to_locale_id(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    calls = []

    def fake_get_ad_locales(*, query=None):
        calls.append(query)
        return [{"id": "6", "name": "English (All)"}] if query == "English" else []

    monkeypatch.setattr(client, "get_ad_locales", fake_get_ad_locales)
    result = client.resolve_targeting_locales({"languages": ["en"], "geo_locations": {"countries": ["US"]}})

    assert result == {"locales": ["6"], "geo_locations": {"countries": ["US"]}}
    assert calls == ["English"]


def test_meta_targeting_search_uses_official_search_parameters(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    captured = {}

    def fake_get(path, params):
        captured.update(path=path, params=params)
        return {"data": [{"id": "6001", "name": "Movies"}]}

    monkeypatch.setattr(client, "_get", fake_get)
    result = client.search_targeting(
        "adregion",
        "new",
        locale="zh_CN",
        country_code="us",
        location_type="region",
        limit=20,
    )

    assert result["data"][0]["id"] == "6001"
    assert captured == {
        "path": "/search",
        "params": {
            "type": "adregion",
            "limit": 20,
            "q": "new",
            "locale": "zh_CN",
            "country_code": "US",
            "location_types": ["region"],
        },
    }


def test_meta_targeting_accepts_object_shaped_search_data(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    client._ad_locales_cache = {}
    monkeypatch.setattr(
        client,
        "_get",
        lambda path, params: {
            "data": {
                "6": {"id": "6", "name": "English (All)"},
            }
        },
    )

    assert client.get_ad_locales(query="English") == [
        {"id": "6", "name": "English (All)"}
    ]


def test_meta_targeting_matches_label_with_display_punctuation(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    monkeypatch.setattr(
        client,
        "get_ad_locales",
        lambda *args, **kwargs: [{"id": "6", "label": "English-All"}],
    )

    assert client.resolve_targeting_locales({"languages": ["en"]}) == {"locales": ["6"]}


def test_meta_targeting_uses_adlocale_key_and_simplified_chinese_alias(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    monkeypatch.setattr(
        client,
        "get_ad_locales",
        lambda *args, **kwargs: [{"id": "9", "labels": {"key": 9, "name": "简体中文"}}],
    )

    assert client.resolve_targeting_locales({"languages": ["zh_CN"]}) == {"locales": ["9"]}


def test_meta_targeting_rejects_missing_remote_locale_as_validation_error(monkeypatch):
    from services.meta.client import MetaClient
    from services.meta.errors import MetaApiError

    client = object.__new__(MetaClient)
    monkeypatch.setattr(client, "get_ad_locales", lambda *args, **kwargs: [])

    with pytest.raises(MetaApiError) as exc_info:
        client.resolve_targeting_locales({"languages": ["en"]})

    assert exc_info.value.category.value == "VALIDATION"
    assert exc_info.value.retryable is False


def test_targeting_preflight_rejects_empty_country_and_gender():
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": []},
        "age_min": 18,
        "age_max": 65,
        "genders": [],
    })
    assert {item["code"] for item in errors} == {"TARGETING_COUNTRY_REQUIRED", "TARGETING_GENDER_INVALID"}


def test_targeting_preflight_rejects_invalid_age_range():
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": ["US"]},
        "age_min": 66,
        "age_max": 18,
        "genders": [1, 2],
    })
    assert {item["code"] for item in errors} == {"TARGETING_AGE_INVALID", "TARGETING_AGE_RANGE_INVALID"}


def test_placement_preflight_accepts_supported_platforms():
    assert placement_preflight_errors("广告组 1 版位", {
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "story"],
        "instagram_positions": ["stream", "story"],
    }) == []


def test_placement_preflight_rejects_unknown_platform_and_position():
    errors = placement_preflight_errors("广告组 1 版位", {
        "publisher_platforms": ["facebook", "wechat"],
        "facebook_positions": ["unknown_position"],
    })
    assert {item["code"] for item in errors} == {"PLACEMENT_PLATFORM_INVALID", "PLACEMENT_POSITION_INVALID"}


def test_targeting_preflight_rejects_audience_and_geo_conflicts():
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": ["US"], "location_types": ["home"]},
        "excluded_geo_locations": {"countries": ["US"]},
        "custom_audiences": [{"id": "aud-1", "ad_account_id": "act_1"}],
        "excluded_custom_audiences": [{"id": "aud-1", "ad_account_id": "act_1"}],
    })
    assert {item["code"] for item in errors} == {"TARGETING_GEO_CONFLICT", "TARGETING_AUDIENCE_CONFLICT"}


def test_targeting_normalization_deduplicates_geo_and_device_values():
    result = normalize_targeting({
        "geo_locations": {
            "countries": ["US", "US"],
            "location_types": ["home", "home", "recent"],
        },
        "device_platforms": ["mobile", "mobile"],
    })
    assert result["geo_locations"] == {
        "countries": ["US"],
        "location_types": ["home", "recent"],
    }
    assert result["device_platforms"] == ["mobile"]


def test_targeting_normalization_preserves_custom_location_objects():
    locations = [
        {"latitude": 37.77, "longitude": -122.42, "radius": 10, "distance_unit": "mile"},
        {"latitude": 37.77, "longitude": -122.42, "radius": 10, "distance_unit": "mile"},
    ]

    result = normalize_targeting({"geo_locations": {"custom_locations": locations}})

    assert result["geo_locations"]["custom_locations"] == locations[:1]


def test_targeting_preflight_rejects_unknown_device_platform():
    errors = targeting_preflight_errors("广告组 1 定向", {
        "geo_locations": {"countries": ["US"]},
        "device_platforms": ["console"],
    })
    assert {item["code"] for item in errors} == {"TARGETING_DEVICE_INVALID"}
