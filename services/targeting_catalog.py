"""Meta 定向目录与配置规范化。

语言不是广告账户资产，不能像 Custom Audience 一样直接从账户列表同步。
本模块提供版本化、可搜索的本地目录，并在发布前把用户输入转换为
Meta targeting 使用的稳定 ID。目录可以在后续由 Meta ``adlocale`` 搜索
结果刷新，但业务配置不保存用户输入的自由文本。
"""

from __future__ import annotations

import re
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
    return result
