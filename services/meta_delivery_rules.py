"""Meta 投放目标与事件源的发布规则。

Meta 的事件源校验应基于广告组的 optimization_goal，而不是基于
Campaign objective 或页面上是否出现了 Pixel 字段。这里集中维护规则，
模板保存、发布预检和最终构建可以复用同一套判断。
"""

import copy
import re
from datetime import datetime, timezone
from typing import Any, Dict, List


# 当前系统支持的网站转化事件源。后续接入 App、Catalog、Offline Dataset
# 时，应扩展 promoted_object 的 source 类型，而不是把 Pixel 变成全局必填。
PIXEL_REQUIRED_OPTIMIZATION_GOALS = frozenset({
    "OFFSITE_CONVERSIONS",
    "VALUE",
    "CONVERSIONS",
})

TRACKING_ASSET_CONFIG_KEYS = frozenset({
    "pixel_id",
    "dataset_id",
    "tracking_asset_type",
    "conversion_event",
    "custom_event_type",
    "promoted_object",
})

STANDARD_CONVERSION_EVENTS = frozenset({
    "PURCHASE",
    "LEAD",
    "COMPLETE_REGISTRATION",
    "ADD_TO_CART",
    "INITIATED_CHECKOUT",
    "ADD_PAYMENT_INFO",
    "VIEW_CONTENT",
    "SEARCH",
    "CONTACT",
    "CUSTOMIZE_PRODUCT",
    "SUBMIT_APPLICATION",
    "START_TRIAL",
    "SUBSCRIBE",
    "SCHEDULE",
    "FIND_LOCATION",
    "DONATE",
})

SUPPORTED_BID_STRATEGIES = frozenset({
    "LOWEST_COST_WITHOUT_CAP",
    "LOWEST_COST_WITH_BID_CAP",
    "COST_CAP",
    "LOWEST_COST_WITH_MIN_ROAS",
})

OBJECTIVE_OPTIMIZATION_GOALS = {
    "OUTCOME_AWARENESS": frozenset({
        "REACH",
        "IMPRESSIONS",
        "AD_RECALL_LIFT",
        "THRUPLAY",
        "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS",
    }),
    "OUTCOME_TRAFFIC": frozenset({"LINK_CLICKS", "LANDING_PAGE_VIEWS", "OFFSITE_CONVERSIONS", "IMPRESSIONS", "REACH", "CONVERSATIONS"}),
    "OUTCOME_SALES": frozenset({"OFFSITE_CONVERSIONS", "VALUE", "CONVERSIONS"}),
    "OUTCOME_ENGAGEMENT": frozenset({"POST_ENGAGEMENT", "THRUPLAY", "EVENT_RESPONSES", "CONVERSATIONS", "IMPRESSIONS"}),
    "OUTCOME_LEADS": frozenset({"LEAD_GENERATION", "OFFSITE_CONVERSIONS", "CONVERSATIONS", "IMPRESSIONS"}),
}

CAMPAIGN_OBJECTIVE_ALIASES = {
    "CONVERSIONS": "OUTCOME_SALES",
    "LINK_CLICKS": "OUTCOME_TRAFFIC",
    "TRAFFIC": "OUTCOME_TRAFFIC",
    "REACH": "OUTCOME_AWARENESS",
    "BRAND_AWARENESS": "OUTCOME_AWARENESS",
    "VIDEO_VIEWS": "OUTCOME_ENGAGEMENT",
    "ENGAGEMENT": "OUTCOME_ENGAGEMENT",
    "LEAD_GENERATION": "OUTCOME_LEADS",
}


def normalized_optimization_goal(value: Any) -> str:
    return str(value or "LINK_CLICKS").strip().upper()


def normalized_campaign_objective(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    return CAMPAIGN_OBJECTIVE_ALIASES.get(normalized, normalized)


def default_optimization_goal(objective: Any) -> str:
    """Use Meta's default traffic performance goal for newly created forms."""

    normalized = normalized_campaign_objective(objective)
    if normalized == "OUTCOME_SALES":
        return "OFFSITE_CONVERSIONS"
    if normalized == "OUTCOME_ENGAGEMENT":
        return "POST_ENGAGEMENT"
    if normalized == "OUTCOME_LEADS":
        return "LEAD_GENERATION"
    if normalized == "OUTCOME_AWARENESS":
        return "REACH"
    return "LANDING_PAGE_VIEWS"


def budget_bid_preflight_errors(
    scope: str,
    budget: Any = None,
    bid_strategy: Any = None,
    bid_amount: Any = None,
    bid_constraints: Any = None,
) -> List[Dict[str, str]]:
    """校验广告组预算和出价参数，避免异步任务收到不可执行配置。"""

    errors: List[Dict[str, str]] = []
    if budget is not None:
        try:
            if float(budget) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"code": "ADSET_BUDGET_INVALID", "message": f"{scope}预算必须大于 0"})

    strategy = str(bid_strategy or "").strip().upper()
    if not strategy:
        return errors
    if strategy not in SUPPORTED_BID_STRATEGIES:
        errors.append({"code": "BID_STRATEGY_INVALID", "message": f"{scope}使用了不支持的出价策略 {strategy}"})
        return errors
    if strategy in {"LOWEST_COST_WITH_BID_CAP", "COST_CAP"}:
        try:
            if float(bid_amount) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"code": "BID_AMOUNT_REQUIRED", "message": f"{scope}的 {strategy} 必须填写大于 0 的竞价金额"})
    if strategy == "LOWEST_COST_WITH_MIN_ROAS":
        floor = bid_constraints.get("roas_average_floor") if isinstance(bid_constraints, dict) else None
        try:
            if float(floor) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append({"code": "BID_CONSTRAINT_INVALID", "message": f"{scope}的最低 ROAS 策略必须填写大于 0 的 roas_average_floor"})
    return errors


def schedule_preflight_errors(budget_type: Any, schedule: Any) -> List[Dict[str, str]]:
    """校验总预算投放的开始/结束时间。"""

    if str(budget_type or "DAILY").strip().upper() != "LIFETIME":
        return []
    if not isinstance(schedule, dict) or not str(schedule.get("end_time") or "").strip():
        return [{"code": "SCHEDULE_END_REQUIRED", "message": "总预算投放必须设置结束时间"}]

    errors: List[Dict[str, str]] = []
    parsed: Dict[str, datetime] = {}
    for field in ("start_time", "end_time"):
        value = str(schedule.get(field) or "").strip()
        if not value:
            continue
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            timestamp = datetime.fromisoformat(normalized)
            if timestamp.tzinfo:
                timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            parsed[field] = timestamp
        except ValueError:
            errors.append({"code": "SCHEDULE_TIME_INVALID", "message": f"{field} 必须是合法的 ISO 8601 时间"})
    if "start_time" in parsed and "end_time" in parsed and parsed["end_time"] <= parsed["start_time"]:
        errors.append({"code": "SCHEDULE_RANGE_INVALID", "message": "结束时间必须晚于开始时间"})
    return errors


def is_pixel_required(optimization_goal: Any) -> bool:
    """当前产品能力下，判断是否必须配置网站 Pixel/Dataset + 转化事件。"""

    return normalized_optimization_goal(optimization_goal) in PIXEL_REQUIRED_OPTIMIZATION_GOALS


def _strip_tracking_asset_fields(config: Dict[str, Any]) -> None:
    """移除当前优化目标不消费的网站 Pixel/Dataset 字段。"""

    for key in TRACKING_ASSET_CONFIG_KEYS - {"promoted_object"}:
        config.pop(key, None)

    promoted_object = config.get("promoted_object")
    if not isinstance(promoted_object, dict):
        return

    # 只清理网站事件源；将来支持 App/Catalog/Offline Dataset 时，
    # 不能因为当前广告组不需要 Pixel 就误删 application_id 等字段。
    has_website_source = any(
        str(promoted_object.get(key) or "").strip()
        for key in ("pixel_id", "dataset_id")
    )
    if not has_website_source:
        return
    promoted_object = dict(promoted_object)
    for key in ("pixel_id", "dataset_id", "conversion_event", "custom_event_type"):
        promoted_object.pop(key, None)
    if promoted_object:
        config["promoted_object"] = promoted_object
    else:
        config.pop("promoted_object", None)


def filter_unused_tracking_assets(
    template_goal: Any,
    creative_config: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """按模板/广告组优化目标过滤无效的 Pixel/Dataset 配置。

    模板级事件源可能被多个广告组继承，因此只要模板默认目标或任一广告组
    使用网站转化优化，就保留模板级事件源；广告组自己的事件源则只在该广告组
    使用转化优化时保留。这样既不会把无关字段发给 Meta，也不会破坏混合目标模板。
    """

    result = copy.deepcopy(creative_config) if isinstance(creative_config, dict) else {}
    adsets = result.get("adsets") if isinstance(result.get("adsets"), list) else []
    has_required_goal = is_pixel_required(template_goal)
    for adset in adsets:
        if isinstance(adset, dict) and is_pixel_required(adset.get("optimization_goal") or template_goal):
            has_required_goal = True
            break

    if not has_required_goal:
        _strip_tracking_asset_fields(result)
        for adset in adsets:
            if isinstance(adset, dict):
                _strip_tracking_asset_fields(adset)
        return result

    for adset in adsets:
        if isinstance(adset, dict) and not is_pixel_required(adset.get("optimization_goal") or template_goal):
            _strip_tracking_asset_fields(adset)
    return result


def _has_pixel_event_source(config: Dict[str, Any]) -> bool:
    return tracking_promoted_object(config) is not None


def tracking_promoted_object(config: Dict[str, Any] | None) -> Dict[str, str] | None:
    """返回网站转化目标实际应发送给 Meta 的规范 promoted_object。

    旧模板可能同时存在顶层字段和 promoted_object，或者 promoted_object
    只剩 page_id 等非网站字段。网站转化目标不能把这些残留对象原样发给
    Meta；优先读取完整的网站对象，缺失时再兼容顶层 Pixel/Dataset 字段。
    同时配置两种事件源时不猜测类型，交给发布预检阻断。
    """

    source = config if isinstance(config, dict) else {}
    promoted = source.get("promoted_object")
    promoted = promoted if isinstance(promoted, dict) else {}

    def clean(value: Any) -> str:
        return str(value or "").strip()

    promoted_dataset_id = clean(promoted.get("dataset_id"))
    promoted_pixel_id = clean(promoted.get("pixel_id"))
    promoted_event = clean(promoted.get("conversion_event") or promoted.get("custom_event_type"))
    if promoted_dataset_id and promoted_pixel_id:
        return None
    if promoted_dataset_id and promoted_event:
        return {"dataset_id": promoted_dataset_id, "conversion_event": promoted_event}
    if promoted_pixel_id and promoted_event:
        return {"pixel_id": promoted_pixel_id, "custom_event_type": promoted_event}

    dataset_id = clean(source.get("dataset_id"))
    pixel_id = clean(source.get("pixel_id"))
    event = clean(source.get("conversion_event") or source.get("custom_event_type"))
    if dataset_id and pixel_id:
        return None
    if dataset_id and event:
        return {"dataset_id": dataset_id, "conversion_event": event}
    if pixel_id and event:
        return {"pixel_id": pixel_id, "custom_event_type": event}
    return None


def _tracking_asset_id(config: Dict[str, Any]) -> str:
    promoted_object = tracking_promoted_object(config)
    if promoted_object:
        return str(promoted_object.get("dataset_id") or promoted_object.get("pixel_id") or "").strip()
    return ""


def _tracking_asset_type(config: Dict[str, Any]) -> str:
    promoted_object = tracking_promoted_object(config)
    if promoted_object and promoted_object.get("dataset_id"):
        return "DATASET"
    if promoted_object and promoted_object.get("pixel_id"):
        return "PIXEL"
    return ""


def _conversion_event(config: Dict[str, Any]) -> str:
    promoted_object = tracking_promoted_object(config)
    if promoted_object:
        return str(promoted_object.get("custom_event_type") or promoted_object.get("conversion_event") or "").strip()
    return ""


def conversion_event_preflight_errors(
    template_goal: Any,
    creative_config: Dict[str, Any] | None,
) -> List[Dict[str, str]]:
    """校验转化事件格式；标准事件和合法自定义事件均允许。"""

    config = creative_config if isinstance(creative_config, dict) else {}
    checks = [("模板默认广告组", template_goal, config)]
    adsets = config.get("adsets") if isinstance(config.get("adsets"), list) else []
    for index, adset in enumerate(adsets, 1):
        if isinstance(adset, dict):
            checks.append((f"广告组 {index}", adset.get("optimization_goal") or template_goal, {**config, **adset}))

    errors: List[Dict[str, str]] = []
    seen = set()
    for scope, goal_value, check_config in checks:
        goal = normalized_optimization_goal(goal_value)
        if not is_pixel_required(goal):
            continue
        event = _conversion_event(check_config)
        if not event or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", event):
            continue
        key = (scope, goal, event)
        if key in seen:
            continue
        seen.add(key)
        errors.append({
            "code": "TRACKING_EVENT_INVALID",
            "message": f"{scope}的转化事件 {event} 格式无效，只能以字母开头并包含字母、数字或下划线",
            "optimization_goal": goal,
            "scope": scope,
        })
    return errors


def objective_optimization_preflight_errors(
    objective: Any,
    template_goal: Any,
    creative_config: Dict[str, Any] | None,
) -> List[Dict[str, str]]:
    """校验当前产品已支持的 Campaign objective / optimization_goal 组合。"""

    campaign_objective = normalized_campaign_objective(objective)
    config = creative_config if isinstance(creative_config, dict) else {}
    checks = [("模板默认广告组", template_goal)]
    adsets = config.get("adsets") if isinstance(config.get("adsets"), list) else []
    for index, adset in enumerate(adsets, 1):
        if isinstance(adset, dict):
            checks.append((f"广告组 {index}", adset.get("optimization_goal") or template_goal))

    errors: List[Dict[str, str]] = []
    seen = set()
    for scope, goal_value in checks:
        goal = normalized_optimization_goal(goal_value)
        key = (scope, goal)
        if key in seen:
            continue
        seen.add(key)
        if campaign_objective == "OUTCOME_APP_PROMOTION":
            errors.append({
                "code": "OBJECTIVE_UNSUPPORTED",
                "message": "当前系统暂不支持 App Promotion，请改用知名度、流量、互动、潜在客户或销售目标",
                "objective": campaign_objective,
                "optimization_goal": goal,
                "scope": scope,
            })
            continue
        allowed_goals = OBJECTIVE_OPTIMIZATION_GOALS.get(campaign_objective)
        if not allowed_goals or goal in allowed_goals:
            continue
        errors.append({
            "code": "OBJECTIVE_OPTIMIZATION_INCOMPATIBLE",
            "message": f"{scope}的推广目标 {campaign_objective} 不支持优化目标 {goal}，可选：{', '.join(sorted(allowed_goals))}",
            "objective": campaign_objective,
            "optimization_goal": goal,
            "scope": scope,
        })
    return errors


def tracking_asset_requirements(
    template_goal: Any,
    creative_config: Dict[str, Any] | None,
) -> List[Dict[str, str]]:
    """提取已填写完整、需要逐账户核验的事件源要求。"""

    config = creative_config if isinstance(creative_config, dict) else {}
    checks = [("模板默认广告组", template_goal, config)]
    adsets = config.get("adsets") if isinstance(config.get("adsets"), list) else []
    for index, adset in enumerate(adsets, 1):
        if isinstance(adset, dict):
            checks.append((f"广告组 {index}", adset.get("optimization_goal") or template_goal, {**config, **adset}))

    requirements: List[Dict[str, str]] = []
    seen = set()
    for scope, goal_value, check_config in checks:
        goal = normalized_optimization_goal(goal_value)
        asset_id = _tracking_asset_id(check_config)
        if not is_pixel_required(goal) or not asset_id or not _has_pixel_event_source(check_config):
            continue
        asset_type = _tracking_asset_type(check_config)
        key = (scope, goal, asset_type, asset_id)
        if key in seen:
            continue
        seen.add(key)
        requirements.append({
            "scope": scope,
            "optimization_goal": goal,
            "asset_id": asset_id,
            "asset_type": asset_type,
        })
    return requirements


def tracking_asset_preflight_errors(
    template_goal: Any,
    creative_config: Dict[str, Any] | None,
) -> List[Dict[str, str]]:
    """返回需要在发布预检阶段阻断的事件源错误。

    只检查实际使用转化优化的广告组；流量、展示、互动、站内表单等
    不使用网站转化事件源的目标不会进入这里。
    """

    config = creative_config if isinstance(creative_config, dict) else {}
    checks = [("模板默认广告组", template_goal, config)]
    adsets = config.get("adsets") if isinstance(config.get("adsets"), list) else []
    for index, adset in enumerate(adsets, 1):
        if not isinstance(adset, dict):
            continue
        # 允许广告组覆盖目标和事件源；未覆盖时沿用模板公共配置。
        merged = {**config, **adset}
        checks.append((f"广告组 {index}", adset.get("optimization_goal") or template_goal, merged))

    errors: List[Dict[str, str]] = []
    seen = set()
    for label, goal_value, check_config in checks:
        goal = normalized_optimization_goal(goal_value)
        if not is_pixel_required(goal) or _has_pixel_event_source(check_config):
            continue
        key = (label, goal)
        if key in seen:
            continue
        seen.add(key)
        errors.append({
            "code": "TRACKING_ASSET_REQUIRED",
            "message": f"{label}使用 {goal}，发布前必须选择 Pixel/数据集并配置转化事件",
            "optimization_goal": goal,
            "scope": label,
        })
    return errors
