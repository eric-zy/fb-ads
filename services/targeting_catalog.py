"""Meta 定向目录与配置规范化。

语言不是广告账户资产，不能像 Custom Audience 一样直接从账户列表同步。
本模块提供版本化、可搜索的本地目录，并在发布前把用户输入转换为
Meta targeting 使用的稳定 ID。目录可以在后续由 Meta ``adlocale`` 搜索
结果刷新，但业务配置不保存用户输入的自由文本。
"""

from __future__ import annotations

import re
import json
from typing import Any, Iterable


# 这是 UI/测试用的稳定基础目录。Meta 的实际可用性仍由账户、目标和 API
# 版本能力预检决定；新增语言应通过目录更新而不是前端硬编码。
LANGUAGE_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "en", "code": "en", "name": "英语", "name_en": "English"},
    {"id": "zh_CN", "code": "zh-CN", "name": "中文（简体）", "name_en": "Chinese (Simplified)"},
    {"id": "zh_TW", "code": "zh-TW", "name": "中文（繁体）", "name_en": "Chinese (Traditional)"},
    {"id": "ja", "code": "ja", "name": "日语", "name_en": "Japanese"},
    {"id": "ko", "code": "ko", "name": "韩语", "name_en": "Korean"},
    {"id": "es", "code": "es", "name": "西班牙语", "name_en": "Spanish"},
    {"id": "pt", "code": "pt", "name": "葡萄牙语", "name_en": "Portuguese"},
    {"id": "fr", "code": "fr", "name": "法语", "name_en": "French"},
    {"id": "de", "code": "de", "name": "德语", "name_en": "German"},
    {"id": "id", "code": "id", "name": "印度尼西亚语", "name_en": "Indonesian"},
    {"id": "th", "code": "th", "name": "泰语", "name_en": "Thai"},
    {"id": "vi", "code": "vi", "name": "越南语", "name_en": "Vietnamese"},
    {"id": "ms", "code": "ms", "name": "马来语", "name_en": "Malay"},
)

PLACEMENT_PLATFORM_OPTIONS = frozenset({
    "facebook",
    "instagram",
    "audience_network",
    "messenger",
})
PLACEMENT_POSITION_OPTIONS = {
    "facebook": frozenset({"feed", "story", "marketplace", "video_feeds", "right_hand_column", "search", "reels", "instream_video", "profile_feed"}),
    "instagram": frozenset({"stream", "story", "reels", "explore", "explore_home", "profile_feed"}),
    "audience_network": frozenset({"classic", "rewarded_video", "instream_video"}),
    "messenger": frozenset({"messenger_home", "story"}),
}

GEO_LOCATION_LIST_FIELDS = frozenset({
    "countries", "regions", "cities", "zips", "custom_locations",
})
LOCATION_TYPE_OPTIONS = frozenset({"home", "recent"})
DEVICE_PLATFORM_OPTIONS = frozenset({"mobile", "desktop"})

# Meta Targeting Search 的公开 type。目录结果会随账户、地区、API 版本和
# Meta 产品策略变化，前端只传 type/q，不在本地复制一份易过期的全量目录。
TARGETING_SEARCH_TYPE_OPTIONS = frozenset({
    "adinterest",
    "adbehavior",
    "addemographic",
    "adlocale",
    "adcountry",
    "adgeolocation",
    "adregion",
    "adcity",
    "adzipcode",
})

_LANGUAGE_BY_ID = {item["id"].lower(): item for item in LANGUAGE_CATALOG}
_LANGUAGE_ALIASES = {
    "中文": ("zh_CN", "zh_TW"),
    "简体中文": ("zh_CN",),
    "繁体中文": ("zh_TW",),
    "普通话": ("zh_CN",),
    "英文": ("en",),
    "英语": ("en",),
    "english": ("en",),
    "chinese": ("zh_CN", "zh_TW"),
}


def search_languages(query: str | None = None, limit: int = 50) -> list[dict[str, str]]:
    """按名称、英文名称、语言代码或 Meta ID 搜索语言。"""
    keyword = re.sub(r"\s+", "", str(query or "")).casefold()
    if not keyword:
        return [dict(item) for item in LANGUAGE_CATALOG[:limit]]
    result = []
    for item in LANGUAGE_CATALOG:
        haystack = "".join(
            str(item.get(key, "")) for key in ("id", "code", "name", "name_en")
        ).replace(" ", "").casefold()
        if keyword in haystack:
            result.append(dict(item))
    return result[:limit]


def normalize_languages(values: Iterable[Any] | None) -> list[str]:
    """把前端语言选择转换成目录 ID，并拒绝未知自由文本。

    接受目录 ID、语言 code 或目录对象；同一个别名可能展开成多个语言，
    例如“中文”会展开为简体和繁体，避免把用户输入原样发给 Meta。
    """
    normalized: list[str] = []
    for raw in values or []:
        if isinstance(raw, dict):
            raw = raw.get("id") or raw.get("meta_id") or raw.get("code") or raw.get("name")
        value = re.sub(r"\s+", "", str(raw or "")).casefold()
        if not value:
            continue
        matches = []
        if value.isdigit():
            # Meta Targeting Search 返回的 locale ID 可直接回填到模板。
            matches = [value]
        elif value in _LANGUAGE_BY_ID:
            matches = [_LANGUAGE_BY_ID[value]["id"]]
        else:
            for item in LANGUAGE_CATALOG:
                if value in {str(item["code"]).casefold(), str(item["name"]).casefold(), str(item["name_en"]).casefold()}:
                    matches.append(item["id"])
            matches.extend(_LANGUAGE_ALIASES.get(value, ()))
        if not matches:
            raise ValueError(f"不支持的 Meta 语言：{raw}")
        for item_id in matches:
            if item_id not in normalized:
                normalized.append(item_id)
    return normalized


def validate_audience_refs(values: Any, field_name: str) -> list[dict[str, Any]]:
    """校验账户级自定义受众引用，不接受没有 ID 的自由文本。"""
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"定向字段 {field_name} 必须是数组")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in values:
        if isinstance(item, str):
            # 兼容旧模板，但明确标记为未解析引用，发布预检时必须补齐账户范围。
            audience_id = item.strip()
            payload: dict[str, Any] = {"id": audience_id, "resolution": "UNRESOLVED"}
        elif isinstance(item, dict):
            audience_id = str(item.get("id") or item.get("meta_audience_id") or "").strip()
            payload = dict(item)
        else:
            raise ValueError(f"定向字段 {field_name} 包含无效受众引用")
        if not audience_id:
            raise ValueError(f"定向字段 {field_name} 的每个受众必须有 Meta Audience ID")
        account_id = str(payload.get("ad_account_id") or payload.get("account_id") or "").strip()
        key = (account_id, audience_id)
        if key in seen:
            continue
        seen.add(key)
        payload["id"] = audience_id
        if account_id:
            payload["ad_account_id"] = account_id
        result.append(payload)
    return result


def normalize_targeting(targeting: dict[str, Any] | None) -> dict[str, Any]:
    """规范化模板/广告组定向，保持未涉及字段不变。"""
    result = dict(targeting or {})
    if result.get("languages") is not None:
        result["languages"] = normalize_languages(result.get("languages"))
    for field in ("custom_audiences", "excluded_custom_audiences", "excluded_audiences"):
        if result.get(field) is not None:
            result[field] = validate_audience_refs(result.get(field), field)
    for field in ("geo_locations", "excluded_geo_locations"):
        value = result.get(field)
        if not isinstance(value, dict):
            continue
        normalized_geo = dict(value)
        for geo_field in GEO_LOCATION_LIST_FIELDS:
            items = normalized_geo.get(geo_field)
            if isinstance(items, list):
                seen = set()
                normalized = []
                for item in items:
                    if geo_field == "custom_locations" and isinstance(item, dict):
                        key = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    else:
                        key = str(item.get("key") if isinstance(item, dict) else item).strip()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    normalized.append(item)
                normalized_geo[geo_field] = normalized
        if isinstance(normalized_geo.get("location_types"), list):
            normalized_geo["location_types"] = list(dict.fromkeys(
                str(item).strip() for item in normalized_geo["location_types"] if str(item).strip()
            ))
        result[field] = normalized_geo
    for field in ("device_platforms", "user_os", "user_device", "wireless_carrier"):
        if isinstance(result.get(field), list):
            result[field] = list(dict.fromkeys(
                str(item).strip() for item in result[field] if str(item).strip()
            ))
    return result


def targeting_preflight_errors(scope: str, targeting: dict[str, Any] | None) -> list[dict[str, str]]:
    """检查当前产品支持的基础定向字段，避免无效配置进入异步投放。"""

    if targeting is None or targeting == {}:
        # 兼容历史模板：未填写定向时仍沿用发布器默认定向。
        return []
    if not isinstance(targeting, dict):
        return [{"code": "TARGETING_INVALID", "message": f"{scope}必须是对象"}]

    errors: list[dict[str, str]] = []
    geo_locations = targeting.get("geo_locations")
    if geo_locations is not None:
        countries = geo_locations.get("countries") if isinstance(geo_locations, dict) else None
        if not isinstance(geo_locations, dict):
            errors.append({"code": "TARGETING_GEO_INVALID", "message": f"{scope}的 geo_locations 必须是对象"})
        elif not any(geo_locations.get(field) for field in GEO_LOCATION_LIST_FIELDS):
            errors.append({
                "code": "TARGETING_COUNTRY_REQUIRED",
                "message": f"{scope}至少需要选择一个国家、地区、城市或邮编",
            })
        elif isinstance(geo_locations.get("location_types"), list):
            invalid = sorted({
                str(value).strip() for value in geo_locations["location_types"]
                if str(value).strip() not in LOCATION_TYPE_OPTIONS
            })
            if invalid:
                errors.append({"code": "TARGETING_LOCATION_TYPE_INVALID", "message": f"{scope}包含不支持的 location_types：{', '.join(invalid)}"})

    excluded_geo = targeting.get("excluded_geo_locations")
    if excluded_geo is not None and not isinstance(excluded_geo, dict):
        errors.append({"code": "TARGETING_EXCLUDED_GEO_INVALID", "message": f"{scope}的 excluded_geo_locations 必须是对象"})
    if isinstance(geo_locations, dict) and isinstance(excluded_geo, dict):
        included_countries = {str(value).strip().upper() for value in geo_locations.get("countries") or []}
        excluded_countries = {str(value).strip().upper() for value in excluded_geo.get("countries") or []}
        overlap = sorted(included_countries & excluded_countries)
        if overlap:
            errors.append({"code": "TARGETING_GEO_CONFLICT", "message": f"{scope}包含和排除的国家/地区重复：{', '.join(overlap)}"})

    age_min = targeting.get("age_min")
    age_max = targeting.get("age_max")
    parsed_min = parsed_max = None
    for field, value in (("age_min", age_min), ("age_max", age_max)):
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            errors.append({"code": "TARGETING_AGE_INVALID", "message": f"{scope}的 {field} 必须是数字"})
            continue
        if parsed < 13 or parsed > 65:
            errors.append({"code": "TARGETING_AGE_INVALID", "message": f"{scope}的年龄必须在 13 至 65 岁之间"})
        if field == "age_min":
            parsed_min = parsed
        else:
            parsed_max = parsed
    if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
        errors.append({"code": "TARGETING_AGE_RANGE_INVALID", "message": f"{scope}的最小年龄不能大于最大年龄"})

    genders = targeting.get("genders")
    if genders is not None:
        if not isinstance(genders, list) or not genders or any(str(gender) not in {"1", "2"} for gender in genders):
            errors.append({"code": "TARGETING_GENDER_INVALID", "message": f"{scope}的性别定向无效，请至少选择男性或女性"})

    included_audiences = {
        str(item.get("id") if isinstance(item, dict) else item).strip()
        for item in targeting.get("custom_audiences") or []
    }
    excluded_audiences = {
        str(item.get("id") if isinstance(item, dict) else item).strip()
        for item in (targeting.get("excluded_custom_audiences") or []) + (targeting.get("excluded_audiences") or [])
    }
    overlap = sorted(value for value in included_audiences & excluded_audiences if value)
    if overlap:
        errors.append({"code": "TARGETING_AUDIENCE_CONFLICT", "message": f"{scope}的包含和排除受众重复：{', '.join(overlap)}"})

    devices = targeting.get("device_platforms")
    if devices is not None:
        if not isinstance(devices, list) or any(str(value).strip() not in DEVICE_PLATFORM_OPTIONS for value in devices):
            errors.append({"code": "TARGETING_DEVICE_INVALID", "message": f"{scope}的 device_platforms 只能是 mobile 或 desktop"})
    return errors


def placement_preflight_errors(scope: str, placement: dict[str, Any] | None) -> list[dict[str, str]]:
    """校验版位平台和位置；未填写版位时表示使用自动版位。"""

    if placement is None or placement == {}:
        return []
    if not isinstance(placement, dict):
        return [{"code": "PLACEMENT_INVALID", "message": f"{scope}必须是对象"}]

    errors: list[dict[str, str]] = []
    platforms = placement.get("publisher_platforms")
    if platforms is not None:
        if not isinstance(platforms, list) or not platforms:
            errors.append({"code": "PLACEMENT_PLATFORM_REQUIRED", "message": f"{scope}至少需要选择一个版位平台"})
        else:
            invalid = sorted({str(value).strip() for value in platforms if str(value).strip() not in PLACEMENT_PLATFORM_OPTIONS})
            if invalid:
                errors.append({"code": "PLACEMENT_PLATFORM_INVALID", "message": f"{scope}包含不支持的版位平台：{', '.join(invalid)}"})

    for platform in PLACEMENT_PLATFORM_OPTIONS:
        field = f"{platform}_positions"
        positions = placement.get(field)
        if positions is None:
            continue
        if not isinstance(positions, list) or any(not str(value).strip() for value in positions):
            errors.append({"code": "PLACEMENT_POSITION_INVALID", "message": f"{scope}的 {field} 必须是非空位置列表"})
            continue
        invalid = sorted({str(value).strip() for value in positions if str(value).strip() not in PLACEMENT_POSITION_OPTIONS[platform]})
        if invalid:
            errors.append({"code": "PLACEMENT_POSITION_INVALID", "message": f"{scope}包含不支持的 {field}：{', '.join(invalid)}"})
    return errors
