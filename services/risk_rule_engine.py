"""风控规则评估引擎。

RC-03 只负责读取本地 Insights 并解释规则结果，不创建执行记录，也不调用
Meta 写接口。真正的动作执行会在后续 RC-04 接入独立的执行器和幂等保护。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

from config.settings import settings
from core.money import to_major
from models import AdAccount, AdInsight, AdSetInsight, AccountInsight, CampaignInsight, RiskExecution, RiskRule, Tenant


SUPPORTED_METRICS = {
    "spend",
    "impressions",
    "clicks",
    "conversions",
    "leads",
    "purchases",
    "conversion_value",
    "revenue",
    "profit",
    "ctr",
    "cpc",
    "cpm",
    "roas",
    "roi",
    "cpa",
    "conversion_rate",
}

OPERATOR_ALIASES = {
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "=": "eq",
    "==": "eq",
    "!=": "neq",
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    operator = OPERATOR_ALIASES.get(str(operator).strip().lower(), str(operator).strip().lower())
    if operator in {"in", "not_in"}:
        values = expected if isinstance(expected, (list, tuple, set)) else [expected]
        result = actual in values
        return result if operator == "in" else not result
    if operator in {"eq", "neq"}:
        left = _number(actual)
        right = _number(expected)
        result = (left == right) if left is not None and right is not None else actual == expected
        return result if operator == "eq" else not result

    left = _number(actual)
    right = _number(expected)
    if left is None or right is None:
        return False
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    return False


def metric_value(metrics: Mapping[str, Any], metric: str) -> Any:
    """读取一个受支持的指标；未知指标返回 None，避免静默命中。"""
    name = str(metric or "").strip().lower()
    if name not in SUPPORTED_METRICS:
        return None
    return metrics.get(name)


def _condition_result(condition: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict:
    metric = str(condition.get("metric") or "").strip().lower()
    operator = OPERATOR_ALIASES.get(
        str(condition.get("operator") or "").strip().lower(),
        str(condition.get("operator") or "").strip().lower(),
    )
    expected = condition.get("value")
    actual = metric_value(metrics, metric)
    matched = bool(metric in SUPPORTED_METRICS and actual is not None and _compare(actual, operator, expected))
    reason = None
    if metric not in SUPPORTED_METRICS:
        reason = "UNSUPPORTED_METRIC"
    elif actual is None:
        reason = "MISSING_METRIC"
    elif operator not in {"gt", "gte", "lt", "lte", "eq", "neq", "in", "not_in"}:
        reason = "UNSUPPORTED_OPERATOR"
    return {
        "metric": metric,
        "operator": operator,
        "expected": expected,
        "actual": actual,
        "matched": matched,
        "reason": reason,
    }


def _scope_matches(scope: Mapping[str, Any], target_type: str, target_id: str) -> bool:
    if not scope:
        return True
    level = str(scope.get("level") or scope.get("type") or "ACCOUNT").upper()
    if level not in {"ACCOUNT", "CAMPAIGN", "ADSET", "AD", "ALL"}:
        return False
    if level != "ALL" and level != target_type.upper():
        return False
    ids = scope.get("ids")
    if not ids:
        return True
    return str(target_id) in {str(item) for item in ids}


def _is_whitelisted(whitelist: Any, account_id: str, target_id: str) -> bool:
    if not whitelist:
        return False
    values = whitelist if isinstance(whitelist, list) else [whitelist]
    for item in values:
        if isinstance(item, Mapping):
            candidate = item.get("id") or item.get("account_id") or item.get("target_id")
            if candidate is not None and str(candidate) in {str(account_id), str(target_id)}:
                return True
        elif str(item) in {str(account_id), str(target_id)}:
            return True
    return False


def kill_switch_enabled(db: Session, tenant_id: Optional[str]) -> bool:
    if bool(getattr(settings, "RISK_AUTOMATION_KILL_SWITCH", False)):
        return True
    if not tenant_id:
        return False
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    risk_settings = (tenant.settings or {}).get("risk_control", {}) if tenant else {}
    return bool(risk_settings.get("kill_switch", False))


def _runtime_seconds(account: AdAccount, now: datetime) -> int:
    created_at = account.created_at
    if not created_at:
        return 0
    return max(0, int((now - created_at).total_seconds()))


def load_account_metrics(
    db: Session,
    account: AdAccount,
    window_days: int = 1,
    as_of: Optional[date] = None,
) -> dict:
    """聚合账户级本地 Insights。

    spend/revenue/profit 等金额字段保留最小货币单位；cpc/cpm 等派生金额按
    主货币单位计算，和 services.analytics.AnalyticsEngine 的口径一致。
    """
    window_days = max(1, min(int(window_days or 1), 90))
    end_date = as_of or datetime.utcnow().date()
    start_date = end_date - timedelta(days=window_days - 1)
    rows = db.query(AccountInsight).filter(
        AccountInsight.ad_account_id == account.id,
        AccountInsight.date >= start_date,
        AccountInsight.date <= end_date,
    ).order_by(AccountInsight.date.asc()).all()

    sum_fields = ("spend", "impressions", "clicks", "conversions", "leads", "purchases", "conversion_value", "revenue", "profit")
    totals = {field: 0 for field in sum_fields}
    nullable_seen = {field: False for field in ("conversion_value", "revenue", "profit")}
    for row in rows:
        for field in sum_fields:
            value = getattr(row, field, None)
            if value is not None:
                totals[field] += int(value or 0) if field not in {"revenue", "profit", "conversion_value"} else int(value)
                if field in nullable_seen:
                    nullable_seen[field] = True

    currency = account.currency or "USD"
    spend_major = to_major(totals["spend"], currency)
    revenue_major = to_major(totals["revenue"], currency)
    metrics = {
        "spend": totals["spend"],
        "impressions": totals["impressions"],
        "clicks": totals["clicks"],
        "conversions": totals["conversions"],
        "leads": totals["leads"],
        "purchases": totals["purchases"],
        "conversion_value": totals["conversion_value"] if nullable_seen["conversion_value"] else None,
        "revenue": totals["revenue"] if nullable_seen["revenue"] else None,
        "profit": totals["profit"] if nullable_seen["profit"] else None,
        "ctr": (totals["clicks"] / totals["impressions"] * 100) if totals["impressions"] else 0,
        "cpc": (spend_major / totals["clicks"]) if totals["clicks"] else 0,
        "cpm": (spend_major / totals["impressions"] * 1000) if totals["impressions"] else 0,
        "roas": (revenue_major / spend_major) if spend_major else 0,
        "roi": ((revenue_major - spend_major) / spend_major) if spend_major else 0,
        "cpa": (spend_major / totals["conversions"]) if totals["conversions"] else 0,
        "conversion_rate": (totals["conversions"] / totals["clicks"] * 100) if totals["clicks"] else 0,
        "currency": currency,
        "window_days": window_days,
        "from_date": start_date.isoformat(),
        "to_date": end_date.isoformat(),
        "data_available": bool(rows),
    }
    return metrics


def load_target_metrics(
    db: Session,
    account: AdAccount,
    target_type: str,
    target_id: str,
    window_days: int = 1,
    as_of: Optional[date] = None,
) -> dict:
    """按账户/系列/广告组/广告读取同一口径的本地指标快照。"""
    target_type = str(target_type or "ACCOUNT").upper()
    if target_type == "ACCOUNT":
        return load_account_metrics(db, account, window_days=window_days, as_of=as_of)

    insight_model = {
        "CAMPAIGN": (CampaignInsight, CampaignInsight.campaign_id),
        "ADSET": (AdSetInsight, AdSetInsight.ad_group_id),
        "AD": (AdInsight, AdInsight.ad_id),
    }.get(target_type)
    if insight_model is None:
        return load_account_metrics(db, account, window_days=window_days, as_of=as_of)

    model, foreign_key = insight_model
    window_days = max(1, min(int(window_days or 1), 90))
    end_date = as_of or datetime.utcnow().date()
    start_date = end_date - timedelta(days=window_days - 1)
    rows = db.query(model).filter(
        foreign_key == target_id,
        model.date >= start_date,
        model.date <= end_date,
    ).order_by(model.date.asc()).all()
    sum_fields = ("spend", "impressions", "clicks", "conversions", "leads", "purchases", "conversion_value", "revenue", "profit")
    totals = {field: 0 for field in sum_fields}
    available = {field: False for field in ("conversion_value", "revenue", "profit")}
    for row in rows:
        for field in sum_fields:
            value = getattr(row, field, None)
            if value is not None:
                totals[field] += int(value or 0)
                if field in available:
                    available[field] = True
    currency = account.currency or "USD"
    spend_major = to_major(totals["spend"], currency)
    revenue_major = to_major(totals["revenue"], currency)
    return {
        "spend": totals["spend"], "impressions": totals["impressions"], "clicks": totals["clicks"],
        "conversions": totals["conversions"], "leads": totals["leads"], "purchases": totals["purchases"],
        "conversion_value": totals["conversion_value"] if available["conversion_value"] else None,
        "revenue": totals["revenue"] if available["revenue"] else None,
        "profit": totals["profit"] if available["profit"] else None,
        "ctr": (totals["clicks"] / totals["impressions"] * 100) if totals["impressions"] else 0,
        "cpc": (spend_major / totals["clicks"]) if totals["clicks"] else 0,
        "cpm": (spend_major / totals["impressions"] * 1000) if totals["impressions"] else 0,
        "roas": (revenue_major / spend_major) if spend_major else 0,
        "roi": ((revenue_major - spend_major) / spend_major) if spend_major else 0,
        "cpa": (spend_major / totals["conversions"]) if totals["conversions"] else 0,
        "conversion_rate": (totals["conversions"] / totals["clicks"] * 100) if totals["clicks"] else 0,
        "currency": currency, "window_days": window_days,
        "from_date": start_date.isoformat(), "to_date": end_date.isoformat(),
        "data_available": bool(rows),
    }


def build_idempotency_key(rule: RiskRule, account_id: str, target_type: str, target_id: str, window_key: str) -> str:
    raw = "|".join((str(rule.id), str(rule.version or 1), str(account_id), target_type.upper(), str(target_id), str(window_key)))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"risk:{rule.id}:{digest}"


class RiskRuleEngine:
    """可解释、可测试的规则评估器。"""

    def __init__(self, db: Session):
        self.db = db

    def _has_cooldown(self, rule: RiskRule, account_id: str, target_type: str, target_id: str, now: datetime) -> bool:
        cooldown = int(rule.cooldown_seconds or 0)
        if cooldown <= 0:
            return False
        cutoff = now - timedelta(seconds=cooldown)
        return self.db.query(RiskExecution.id).filter(
            RiskExecution.rule_id == rule.id,
            RiskExecution.ad_account_id == account_id,
            RiskExecution.target_type == target_type.upper(),
            RiskExecution.target_id == target_id,
            RiskExecution.created_at >= cutoff,
            # FAILED 允许通过显式 retry 重试；只有已命中/执行中的记录才触发冷却。
            RiskExecution.status.in_(["MATCHED", "RUNNING", "SUCCESS"]),
        ).first() is not None

    def evaluate(
        self,
        rule: RiskRule,
        account_id: str,
        *,
        target_type: str = "ACCOUNT",
        target_id: Optional[str] = None,
        metrics: Optional[Mapping[str, Any]] = None,
        runtime_seconds: int = 0,
        window_key: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> dict:
        now = now or datetime.utcnow()
        target_id = str(target_id or account_id)
        config = rule.to_config()
        metrics = dict(metrics or {})
        window_key = window_key or now.date().isoformat()
        result = {
            "matched": False,
            "status": "SKIPPED",
            "reason": None,
            "conditions": [],
            "action": rule.action_on_trigger or "ALERT",
            "rule_version": int(rule.version or 1),
            "idempotency_key": build_idempotency_key(rule, account_id, target_type, target_id, window_key),
        }
        if not config["is_active"]:
            result["reason"] = "RULE_INACTIVE"
            return result
        if kill_switch_enabled(self.db, rule.tenant_id):
            result["reason"] = "KILL_SWITCH"
            return result
        if not _scope_matches(config["scope"], target_type, target_id):
            result["reason"] = "SCOPE_MISMATCH"
            return result
        if _is_whitelisted(config["whitelist"], account_id, target_id):
            result["reason"] = "WHITELIST"
            return result
        if int(config["min_spend"]) > int(metrics.get("spend") or 0):
            result["reason"] = "MIN_SPEND"
            return result
        if int(config["min_runtime"]) > int(runtime_seconds or 0):
            result["reason"] = "MIN_RUNTIME"
            return result
        if self._has_cooldown(rule, account_id, target_type, target_id, now):
            result["reason"] = "COOLDOWN"
            return result

        conditions = config["conditions"]
        if not conditions:
            result["reason"] = "NO_CONDITIONS"
            return result
        result["conditions"] = [_condition_result(item, metrics) for item in conditions if isinstance(item, Mapping)]
        matched_values = [item["matched"] for item in result["conditions"]]
        logic = config["logic"] if config["logic"] in {"AND", "OR"} else "AND"
        matched = all(matched_values) if logic == "AND" else any(matched_values)
        result["matched"] = matched
        result["status"] = "MATCHED" if matched else "NOT_MATCHED"
        result["reason"] = "CONDITIONS_MATCHED" if matched else "CONDITIONS_NOT_MATCHED"
        return result
