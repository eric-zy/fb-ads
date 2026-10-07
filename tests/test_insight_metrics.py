import pytest
from decimal import Decimal

from services.ads_manager import AdsManager
from services.analytics import AnalyticsEngine


def test_action_metrics_separate_conversion_types_and_value():
    actions = [
        {"action_type": "link_click", "value": "20"},
        {"action_type": "landing_page_view", "value": "15"},
        {"action_type": "lead", "value": "3"},
        {"action_type": "purchase", "value": "2"},
    ]
    values = [{"action_type": "purchase", "value": "49.90"}]

    result = AdsManager._parse_action_metrics(actions, values)

    assert result["link_clicks"] == 20
    assert result["landing_page_views"] == 15
    assert result["leads"] == 3
    assert result["purchases"] == 2
    assert result["conversions"] == 5
    assert result["conversion_value"] == Decimal("49.90")


def test_action_value_preserves_large_decimal_precision():
    result = AdsManager._parse_action_metrics([], [{"action_type": "purchase", "value": "90071992547409.93"}])
    assert result["conversion_value"] == Decimal("90071992547409.93")


def test_calculate_metrics_uses_click_denominator_for_conversion_rate():
    metrics = AnalyticsEngine(None).calculate_metrics(
        spend=100, impressions=1000, clicks=200, conversions=10
    )

    assert metrics["ctr"] == pytest.approx(20.0)
    assert metrics["cpc"] == pytest.approx(0.5)
    assert metrics["cpm"] == pytest.approx(100.0)
    assert metrics["conversion_rate"] == pytest.approx(5.0)


def test_aliases_do_not_double_count_omni_purchase_lead_or_clicks():
    actions = [{"action_type": key, "value": "2"} for key in ("purchase", "omni_purchase", "lead", "omni_lead", "link_click", "inline_link_click")]
    values = [{"action_type": key, "value": "10.50"} for key in ("purchase", "omni_purchase")]
    result = AdsManager._parse_action_metrics(actions, values)
    assert result["purchases"] == result["leads"] == result["link_clicks"] == 2
    assert result["conversions"] == 4
    assert result["conversion_value"] == Decimal("10.50")


def test_zero_omni_metric_does_not_fall_back_to_duplicate_nonzero_alias():
    result = AdsManager._parse_action_metrics([{"action_type": "omni_purchase", "value": "0"}, {"action_type": "purchase", "value": "2"}])
    assert result["purchases"] == 0
