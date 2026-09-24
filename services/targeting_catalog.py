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
GEO_REFERENCE_FIELDS = ("regions", "cities", "zips")
LOCATION_TYPE_OPTIONS = frozenset({"home", "recent"})
DEVICE_PLATFORM_OPTIONS = frozenset({"mobile", "desktop"})

# 投放表单历史上允许输入国家名称，Meta ``geo_locations.countries``
# 实际只接受 ISO 3166-1 alpha-2 代码。保留常用中英文别名，避免旧模板
# 因为“美国、加拿大、英国”这类可读值在异步发布阶段才失败。
_COUNTRY_ALIASES = {
    "中国": "CN", "中国大陆": "CN", "china": "CN", "中国香港": "HK", "香港": "HK", "hongkong": "HK",
    "中国澳门": "MO", "澳门": "MO", "macao": "MO", "中国台湾": "TW", "台湾": "TW", "taiwan": "TW",
    "美国": "US", "美國": "US", "美国合众国": "US", "unitedstates": "US", "unitedstatesofamerica": "US", "usa": "US",
    "加拿大": "CA", "canada": "CA", "英国": "GB", "英國": "GB", "uk": "GB", "unitedkingdom": "GB",
    "澳大利亚": "AU", "澳洲": "AU", "australia": "AU", "新西兰": "NZ", "newzealand": "NZ",
    "日本": "JP", "japan": "JP", "韩国": "KR", "南韩": "KR", "korea": "KR", "southkorea": "KR",
    "新加坡": "SG", "singapore": "SG", "马来西亚": "MY", "malaysia": "MY", "泰国": "TH", "thailand": "TH",
    "越南": "VN", "vietnam": "VN", "印度尼西亚": "ID", "印尼": "ID", "indonesia": "ID", "印度": "IN", "india": "IN",
    "德国": "DE", "germany": "DE", "法国": "FR", "france": "FR", "意大利": "IT", "italy": "IT",
    "西班牙": "ES", "spain": "ES", "葡萄牙": "PT", "portugal": "PT", "荷兰": "NL", "netherlands": "NL",
    "比利时": "BE", "belgium": "BE", "瑞士": "CH", "switzerland": "CH", "爱尔兰": "IE", "ireland": "IE",
    "瑞典": "SE", "sweden": "SE", "挪威": "NO", "norway": "NO", "丹麦": "DK", "denmark": "DK",
    "芬兰": "FI", "finland": "FI", "波兰": "PL", "poland": "PL", "奥地利": "AT", "austria": "AT",
    "巴西": "BR", "brazil": "BR", "墨西哥": "MX", "mexico": "MX", "阿根廷": "AR", "argentina": "AR",
    "阿联酋": "AE", "unitedarabemirates": "AE", "沙特阿拉伯": "SA", "saudiarabia": "SA", "南非": "ZA", "southafrica": "ZA",
    "俄罗斯": "RU", "俄羅斯": "RU", "russia": "RU", "乌克兰": "UA", "ukraine": "UA", "土耳其": "TR", "turkey": "TR",
    "菲律宾": "PH", "菲律賓": "PH", "philippines": "PH",
}


def normalize_country_code(value: Any) -> str | None:
    """把国家显示名、国家代码或目录对象转换为 Meta 国家代码。"""

    raw = value
    if isinstance(raw, dict):
        raw = raw.get("id") or raw.get("key") or raw.get("code") or raw.get("name")
    text = re.sub(r"\s+", "", str(raw or "")).strip()
    if not text:
        return None
    match = re.search(r"[\(（]([A-Za-z]{2})[\)）]$", text)
    if match:
        return match.group(1).upper()
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    return _COUNTRY_ALIASES.get(text.casefold())

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


def _geo_reference_key(value: Any, field_name: str) -> str | None:
    """提取 Meta 地区/城市/邮编目录项的稳定 key。

    Meta Search 返回的对象可能同时包含 name、labels、search_type 等展示字段，
    这些字段不能直接透传到 AdSet。旧模板也可能保存为字符串，因此这里只接受
    能识别为目录 key 的值，并在 normalize_targeting 中统一转成 ``{"key": ...}``。
    """

    raw = value
    if isinstance(value, dict):
        raw = value.get("key") or value.get("id") or value.get("value")
    text = str(raw or "").strip()
    if not text:
        return None
    if field_name in {"regions", "cities"}:
        return text if re.fullmatch(r"\d+", text) else None
    # 国际邮编可能包含字母、连字符或国家前缀，但应至少包含数字；
    # 这样可以拦截把城市名称直接填入 zips 的旧配置。
    return text if re.fullmatch(r"[A-Za-z0-9:_ -]+", text) and any(char.isdigit() for char in text) else None


def _interest_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("id") or value.get("key") or value.get("value")
    text = str(raw or "").strip()
    return text or None


def _normalize_interest_refs(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        raise ValueError("flexible_spec.interests 必须是 Meta 兴趣对象数组")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        interest_id = _interest_id(item)
        if not interest_id:
            raise ValueError("兴趣必须从 Meta 兴趣目录选择并包含 ID，不能只填写兴趣名称")
        name = str(item.get("name") or item.get("label") or interest_id).strip()
        if interest_id in seen:
            continue
        seen.add(interest_id)
        result.append({"id": interest_id, "name": name})
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
                    if geo_field == "countries":
                        country_code = normalize_country_code(item)
                        if country_code:
                            item = country_code
                    elif geo_field in GEO_REFERENCE_FIELDS:
                        item = {"key": _geo_reference_key(item, geo_field)}
                        if not item["key"]:
                            raise ValueError(f"geo_locations.{geo_field} 必须使用 Meta 返回的稳定 key，不能填写显示名称")
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
    flexible_spec = result.get("flexible_spec")
    if flexible_spec is not None:
        if not isinstance(flexible_spec, list):
            raise ValueError("flexible_spec 必须是数组")
        normalized_specs = []
        for spec in flexible_spec:
            if not isinstance(spec, dict):
                raise ValueError("flexible_spec 的每一项必须是对象")
            normalized_spec = dict(spec)
            if "interests" in normalized_spec:
                normalized_spec["interests"] = _normalize_interest_refs(normalized_spec["interests"])
            normalized_specs.append(normalized_spec)
        result["flexible_spec"] = normalized_specs
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
        if isinstance(geo_locations, dict) and countries is not None:
            if not isinstance(countries, list):
                errors.append({"code": "TARGETING_COUNTRY_INVALID", "message": f"{scope}的 countries 必须是国家代码数组"})
            else:
                invalid = sorted({str(value).strip() for value in countries if value and not normalize_country_code(value)})
                if invalid:
                    errors.append({
                        "code": "TARGETING_COUNTRY_CODE_INVALID",
                        "message": f"{scope}的国家/地区无法识别：{', '.join(invalid)}。请使用国家名称或 ISO 两位代码，例如 US、CA、GB",
                    })
        if isinstance(geo_locations, dict):
            for geo_field in GEO_REFERENCE_FIELDS:
                values = geo_locations.get(geo_field)
                if values is None:
                    continue
                if not isinstance(values, list):
                    errors.append({
                        "code": "TARGETING_GEO_KEY_INVALID",
                        "message": f"{scope}的 {geo_field} 必须是 Meta 目录 key 数组",
                    })
                    continue
                invalid = [
                    str(value.get("name") or value.get("id") or value) if isinstance(value, dict) else str(value)
                    for value in values
                    if not _geo_reference_key(value, geo_field)
                ]
                if invalid:
                    errors.append({
                        "code": "TARGETING_GEO_KEY_INVALID",
                        "message": f"{scope}的 {geo_field} 必须使用 Meta 返回的稳定 key，不能填写显示名称：{', '.join(invalid[:5])}",
                    })
        if isinstance(geo_locations, dict) and isinstance(geo_locations.get("location_types"), list):
            invalid = sorted({
                str(value).strip() for value in geo_locations["location_types"]
                if str(value).strip() not in LOCATION_TYPE_OPTIONS
            })
            if invalid:
                errors.append({"code": "TARGETING_LOCATION_TYPE_INVALID", "message": f"{scope}包含不支持的 location_types：{', '.join(invalid)}"})

    excluded_geo = targeting.get("excluded_geo_locations")
    if excluded_geo is not None and not isinstance(excluded_geo, dict):
        errors.append({"code": "TARGETING_EXCLUDED_GEO_INVALID", "message": f"{scope}的 excluded_geo_locations 必须是对象"})
    elif isinstance(excluded_geo, dict) and excluded_geo.get("countries") is not None:
        excluded_countries = excluded_geo.get("countries")
        if not isinstance(excluded_countries, list):
            errors.append({"code": "TARGETING_COUNTRY_INVALID", "message": f"{scope}排除的 countries 必须是国家代码数组"})
        else:
            invalid = sorted({str(value).strip() for value in excluded_countries if value and not normalize_country_code(value)})
            if invalid:
                errors.append({
                    "code": "TARGETING_COUNTRY_CODE_INVALID",
                    "message": f"{scope}排除的国家/地区无法识别：{', '.join(invalid)}。请使用国家名称或 ISO 两位代码，例如 US、CA、GB",
                })
    if isinstance(excluded_geo, dict):
        for geo_field in GEO_REFERENCE_FIELDS:
            values = excluded_geo.get(geo_field)
            if values is None:
                continue
            if not isinstance(values, list):
                errors.append({
                    "code": "TARGETING_GEO_KEY_INVALID",
                    "message": f"{scope}排除的 {geo_field} 必须是 Meta 目录 key 数组",
                })
                continue
            invalid = [
                str(value.get("name") or value.get("id") or value) if isinstance(value, dict) else str(value)
                for value in values
                if not _geo_reference_key(value, geo_field)
            ]
            if invalid:
                errors.append({
                    "code": "TARGETING_GEO_KEY_INVALID",
                    "message": f"{scope}排除的 {geo_field} 必须使用 Meta 返回的稳定 key，不能填写显示名称：{', '.join(invalid[:5])}",
                })
    if isinstance(geo_locations, dict) and isinstance(excluded_geo, dict):
        included_countries = {
            normalize_country_code(value) or str(value).strip().upper()
            for value in geo_locations.get("countries") or []
        }
        excluded_countries = {
            normalize_country_code(value) or str(value).strip().upper()
            for value in excluded_geo.get("countries") or []
        }
        overlap = sorted(included_countries & excluded_countries)
        if overlap:
            errors.append({"code": "TARGETING_GEO_CONFLICT", "message": f"{scope}包含和排除的国家/地区重复：{', '.join(overlap)}"})

    flexible_spec = targeting.get("flexible_spec")
    if flexible_spec is not None:
        if not isinstance(flexible_spec, list):
            errors.append({"code": "TARGETING_INTEREST_INVALID", "message": f"{scope}的 flexible_spec 必须是数组"})
        else:
            for spec in flexible_spec:
                if not isinstance(spec, dict) or "interests" not in spec:
                    continue
                interests = spec.get("interests")
                if not isinstance(interests, list):
                    errors.append({"code": "TARGETING_INTEREST_INVALID", "message": f"{scope}的兴趣必须是 Meta 兴趣对象数组"})
                    continue
                invalid = [
                    str(item.get("name") or item) if isinstance(item, dict) else str(item)
                    for item in interests
                    if not _interest_id(item)
                ]
                if invalid:
                    errors.append({
                        "code": "TARGETING_INTEREST_INVALID",
                        "message": f"{scope}的兴趣必须从 Meta 兴趣目录选择并包含 ID，不能只填写名称：{', '.join(invalid[:5])}",
                    })

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
