"""Meta 投放目标与事件源的发布规则。

Meta 的事件源校验应基于广告组的 optimization_goal，而不是基于
Campaign objective 或页面上是否出现了 Pixel 字段。这里集中维护规则，
模板保存、发布预检和最终构建可以复用同一套判断。
"""

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
    "OUTCOME_TRAFFIC": frozenset({"LINK_CLICKS", "LANDING_PAGE_VIEWS", "OFFSITE_CONVERSIONS", "IMPRESSIONS", "REACH"}),
    "OUTCOME_SALES": frozenset({"OFFSITE_CONVERSIONS", "VALUE", "CONVERSIONS"}),
    "OUTCOME_ENGAGEMENT": frozenset({"POST_ENGAGEMENT", "THRUPLAY", "EVENT_RESPONSES", "IMPRESSIONS"}),
    "OUTCOME_LEADS": frozenset({"LEAD_GENERATION", "OFFSITE_CONVERSIONS", "IMPRESSIONS"}),
}


def normalized_optimization_goal(value: Any) -> str:
    return str(value or "LINK_CLICKS").strip().upper()


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


def _has_pixel_event_source(config: Dict[str, Any]) -> bool:
    promoted_object = config.get("promoted_object")
    if isinstance(promoted_object, dict):
        pixel_id = promoted_object.get("pixel_id") or promoted_object.get("dataset_id")
        event = promoted_object.get("custom_event_type") or promoted_object.get("conversion_event")
        if str(pixel_id or "").strip() and str(event or "").strip():
            return True

    pixel_id = config.get("dataset_id") or config.get("pixel_id")
    event = config.get("conversion_event") or config.get("custom_event_type")
    return bool(str(pixel_id or "").strip() and str(event or "").strip())


def _tracking_asset_id(config: Dict[str, Any]) -> str:
    promoted_object = config.get("promoted_object")
    if isinstance(promoted_object, dict):
        value = promoted_object.get("pixel_id") or promoted_object.get("dataset_id")
        if str(value or "").strip():
            return str(value).strip()
    return str(config.get("dataset_id") or config.get("pixel_id") or "").strip()


def _conversion_event(config: Dict[str, Any]) -> str:
    promoted_object = config.get("promoted_object")
    if isinstance(promoted_object, dict):
        value = promoted_object.get("custom_event_type") or promoted_object.get("conversion_event")
        if str(value or "").strip():
            return str(value).strip()
    return str(config.get("conversion_event") or config.get("custom_event_type") or "").strip()


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

    campaign_objective = str(objective or "").strip().upper()
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
        allowed_goals = OBJECTIVE_OPTIMIZATION_GOALS.get(campaign_objective)
        if not allowed_goals or goal in allowed_goals:
            continue
        key = (scope, goal)
        if key in seen:
            continue
        seen.add(key)
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
        key = (scope, goal, asset_id)
        if key in seen:
            continue
        seen.add(key)
        requirements.append({"scope": scope, "optimization_goal": goal, "asset_id": asset_id})
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
