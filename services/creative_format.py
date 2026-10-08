"""Canonical creative format values shared by template validation and payload building."""

from __future__ import annotations


SINGLE_IMAGE_VIDEO = "SINGLE_IMAGE_VIDEO"
CAROUSEL = "CAROUSEL"

# MULTI_AD was the old UI name for "one image/video per ad". Keep accepting it
# when reading existing templates, but never emit it from new requests.
_SINGLE_ALIASES = {
    "SINGLE_IMAGE_VIDEO",
    "SINGLE_IMAGE_OR_VIDEO",
    "SINGLE_IMAGE",
    "SINGLE_VIDEO",
    "MULTI_AD",
    "SINGLE_MEDIA",
    "",
}


def normalize_creative_format(value: object) -> str:
    """Return the canonical Meta-facing format or raise for an unknown value."""

    normalized = str(value or "").strip().upper()
    if normalized in _SINGLE_ALIASES:
        return SINGLE_IMAGE_VIDEO
    if normalized == CAROUSEL:
        return CAROUSEL
    raise ValueError("创意格式必须是单图片或视频（SINGLE_IMAGE_VIDEO）或轮播（CAROUSEL）")


def carousel_cta_mode(config: dict) -> str:
    """Validate card button selection independently of destination URLs."""
    mode = str(config.get("carousel_cta_mode") or "ALL").strip().upper()
    if mode not in {"ALL", "CUSTOM"}:
        raise ValueError("轮播跳转按钮模式只能是 ALL 或 CUSTOM")
    cards = config.get("carousel_cards") or config.get("creatives") or []
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            raise ValueError(f"轮播卡片 {index} 配置必须是对象")
        if "show_cta" in card and not isinstance(card["show_cta"], bool):
            raise ValueError(f"轮播卡片 {index} 的 show_cta 必须是布尔值")
    return mode
