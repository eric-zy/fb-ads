import pytest

from services.meta_creative_options import normalize_cta


def test_meta_cta_values_are_normalized():
    assert normalize_cta("learn_more") == "LEARN_MORE"
    assert normalize_cta("NO_BUTTON") == "NO_BUTTON"
    assert normalize_cta("") is None


def test_unknown_cta_is_rejected():
    with pytest.raises(ValueError, match="行动号召"):
        normalize_cta("NOT_A_META_CTA")
