import pytest

from services.targeting_catalog import normalize_languages, normalize_targeting, validate_audience_refs


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


def test_meta_targeting_resolves_product_language_to_locale_id(monkeypatch):
    from services.meta.client import MetaClient

    client = object.__new__(MetaClient)
    monkeypatch.setattr(client, "get_ad_locales", lambda: [{"id": "6", "name": "English (All)"}])
    result = client.resolve_targeting_locales({"languages": ["en"], "geo_locations": {"countries": ["US"]}})

    assert result == {"locales": ["6"], "geo_locations": {"countries": ["US"]}}
