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
