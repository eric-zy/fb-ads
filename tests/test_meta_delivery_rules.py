from services.meta_delivery_rules import budget_bid_preflight_errors, conversion_event_preflight_errors, default_optimization_goal, objective_optimization_preflight_errors, schedule_preflight_errors, tracking_asset_preflight_errors, tracking_asset_requirements


def test_traffic_optimization_does_not_require_pixel():
    assert tracking_asset_preflight_errors(
        "LINK_CLICKS",
        {"adsets": [{"optimization_goal": "LANDING_PAGE_VIEWS"}]},
    ) == []


def test_conversion_optimization_is_blocked_without_pixel_event():
    errors = tracking_asset_preflight_errors("OFFSITE_CONVERSIONS", {})
    assert errors[0]["code"] == "TRACKING_ASSET_REQUIRED"
    assert errors[0]["optimization_goal"] == "OFFSITE_CONVERSIONS"


def test_conversion_optimization_accepts_promoted_object():
    assert tracking_asset_preflight_errors(
        "OFFSITE_CONVERSIONS",
        {"promoted_object": {"pixel_id": "pixel-1", "custom_event_type": "PURCHASE"}},
    ) == []


def test_only_conversion_adset_is_blocked():
    errors = tracking_asset_preflight_errors(
        "LINK_CLICKS",
        {"adsets": [
            {"optimization_goal": "LINK_CLICKS"},
            {"optimization_goal": "VALUE"},
        ]},
    )
    assert len(errors) == 1
    assert errors[0]["scope"] == "广告组 2"


def test_tracking_requirements_are_extracted_for_account_validation():
    requirements = tracking_asset_requirements(
        "LINK_CLICKS",
        {
            "promoted_object": {"pixel_id": "pixel-1", "custom_event_type": "PURCHASE"},
            "adsets": [{"optimization_goal": "OFFSITE_CONVERSIONS"}],
        },
    )
    assert requirements == [{
        "scope": "广告组 1",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "asset_id": "pixel-1",
    }]


def test_standard_and_custom_conversion_events_are_allowed():
    assert conversion_event_preflight_errors(
        "OFFSITE_CONVERSIONS",
        {"promoted_object": {"pixel_id": "pixel-1", "custom_event_type": "PURCHASE"}},
    ) == []
    assert conversion_event_preflight_errors(
        "OFFSITE_CONVERSIONS",
        {"promoted_object": {"pixel_id": "pixel-1", "custom_event_type": "my_custom_event_01"}},
    ) == []


def test_invalid_conversion_event_is_blocked_in_preflight():
    errors = conversion_event_preflight_errors(
        "OFFSITE_CONVERSIONS",
        {"promoted_object": {"pixel_id": "pixel-1", "custom_event_type": "下单事件"}},
    )
    assert errors[0]["code"] == "TRACKING_EVENT_INVALID"


def test_sales_click_optimization_is_blocked_in_preflight():
    errors = objective_optimization_preflight_errors(
        "OUTCOME_SALES",
        "LINK_CLICKS",
        {},
    )
    assert errors[0]["code"] == "OBJECTIVE_OPTIMIZATION_INCOMPATIBLE"


def test_traffic_click_optimization_is_allowed():
    assert objective_optimization_preflight_errors("OUTCOME_TRAFFIC", "LINK_CLICKS", {}) == []


def test_meta_traffic_performance_goals_are_allowed():
    for goal in ("LANDING_PAGE_VIEWS", "LINK_CLICKS", "REACH", "CONVERSATIONS", "IMPRESSIONS"):
        assert objective_optimization_preflight_errors("OUTCOME_TRAFFIC", goal, {}) == []


def test_default_traffic_performance_goal_matches_meta_ui():
    assert default_optimization_goal("OUTCOME_TRAFFIC") == "LANDING_PAGE_VIEWS"


def test_leads_can_use_onsite_lead_generation_without_pixel():
    assert objective_optimization_preflight_errors("OUTCOME_LEADS", "LEAD_GENERATION", {}) == []
    assert tracking_asset_preflight_errors("LEAD_GENERATION", {}) == []


def test_engagement_optimization_does_not_require_pixel():
    assert objective_optimization_preflight_errors("OUTCOME_ENGAGEMENT", "POST_ENGAGEMENT", {}) == []
    assert tracking_asset_preflight_errors("POST_ENGAGEMENT", {}) == []


def test_bid_cap_requires_positive_bid_amount():
    errors = budget_bid_preflight_errors("广告组 1", 10, "COST_CAP", 0)
    assert [item["code"] for item in errors] == ["BID_AMOUNT_REQUIRED"]


def test_budget_and_bid_strategy_are_validated():
    errors = budget_bid_preflight_errors("广告组 1", 0, "UNKNOWN", None)
    assert {item["code"] for item in errors} == {"ADSET_BUDGET_INVALID", "BID_STRATEGY_INVALID"}


def test_min_roas_requires_positive_constraint():
    errors = budget_bid_preflight_errors("模板", 50, "LOWEST_COST_WITH_MIN_ROAS", None, {})
    assert errors[0]["code"] == "BID_CONSTRAINT_INVALID"


def test_min_roas_accepts_valid_constraint():
    assert budget_bid_preflight_errors(
        "模板", 50, "LOWEST_COST_WITH_MIN_ROAS", None, {"roas_average_floor": 1.5}
    ) == []


def test_lifetime_budget_requires_end_time():
    errors = schedule_preflight_errors("LIFETIME", {"start_time": "2026-09-22T10:00:00Z"})
    assert errors[0]["code"] == "SCHEDULE_END_REQUIRED"


def test_schedule_end_must_be_after_start():
    errors = schedule_preflight_errors("LIFETIME", {
        "start_time": "2026-09-22T12:00:00Z",
        "end_time": "2026-09-22T11:00:00Z",
    })
    assert errors[0]["code"] == "SCHEDULE_RANGE_INVALID"
