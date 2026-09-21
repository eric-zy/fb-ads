"""风控中心 API：总览、风险事件、规则配置和执行记录。"""

import math
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.audit import record_audit
from core.auth import get_current_active_user
from core.database import get_db
from core.tenant import effective_tenant_id
from models import AdAccount, RiskEvent, RiskExecution, RiskRule, SyncAlert, User
from models.risk_control import RiskEventType, RiskLevel
from models.tenant import UserRole
from services.account_access import accessible_account_ids
from services.risk_action_service import rule_targets
from services.risk_rule_engine import RiskRuleEngine, load_target_metrics


router = APIRouter(prefix="/api/v1/risk-control", tags=["风控中心"])


class RiskRulePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=4000)
    rule_type: str = Field(..., min_length=1, max_length=100)
    is_active: bool = True
    scope: Dict[str, Any] = Field(default_factory=dict)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    logic: str = Field(default="AND", pattern="^(AND|OR|and|or)$")
    threshold: Optional[float] = None
    threshold_unit: Optional[str] = Field(default=None, max_length=50)
    min_spend: int = Field(default=0, ge=0)
    min_runtime: int = Field(default=0, ge=0)
    cooldown_seconds: int = Field(default=0, ge=0)
    max_actions_per_run: int = Field(default=100, ge=1, le=10000)
    dry_run: bool = False
    whitelist: List[Any] = Field(default_factory=list)
    action_on_trigger: str = Field(default="ALERT", max_length=255)
    alert_channels: Optional[str] = Field(default=None, max_length=500)
    priority: int = Field(default=0, ge=0, le=100000)


class RiskRuleTogglePayload(BaseModel):
    is_active: bool


class RiskEventResolvePayload(BaseModel):
    resolution: str = Field(..., min_length=1, max_length=2000)


class RiskRuleDryRunPayload(BaseModel):
    account_ids: List[str] = Field(default_factory=list)
    window_days: int = Field(default=1, ge=1, le=90)


def _visible_account_query(db: Session, current_user: User):
    query = db.query(AdAccount)
    visible = accessible_account_ids(db, current_user)
    if visible is not None:
        if not visible:
            return query.filter(False)
        query = query.filter(AdAccount.id.in_(visible))
    return query


def _get_visible_account(db: Session, value: str, current_user: User) -> AdAccount:
    account = _visible_account_query(db, current_user).filter(
        or_(AdAccount.id == value, AdAccount.account_id == value)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="广告账户不存在或无权访问")
    return account


def _require_rule_manager(current_user: User) -> User:
    role = UserRole.normalize(current_user.role)
    if (
        current_user.is_admin()
        or role == UserRole.MANAGER.value
        or "risk_rule:manage" in (current_user.permissions or [])
    ):
        return current_user
    raise HTTPException(status_code=403, detail="需要风控规则管理权限")


def _page_meta(total: int, page: int, page_size: int) -> dict:
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": math.ceil(total / page_size) if total else 0,
    }


def _risk_level(score: float, critical_count: int = 0) -> str:
    if critical_count > 0 or score >= 0.85:
        return "critical"
    if score >= 0.7:
        return "high"
    if score >= 0.3:
        return "medium"
    return "low"


def _event_to_dict(event: RiskEvent) -> dict:
    return {
        "id": event.id,
        "source": "RISK_EVENT",
        "ad_account_id": event.ad_account_id,
        "event_type": event.event_type.value if event.event_type else None,
        "risk_level": event.risk_level.value if event.risk_level else None,
        "risk_score": event.risk_score,
        "title": event.title,
        "description": event.description,
        "related_campaign_id": event.related_campaign_id,
        "related_ad_id": event.related_ad_id,
        "is_resolved": bool(event.is_resolved),
        "resolution": event.resolution,
        "resolved_by": event.resolved_by,
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
        "auto_action_taken": event.auto_action_taken,
        "requires_manual_review": bool(event.requires_manual_review),
        "notification_status": event.notification_status,
        "notification_attempts": event.notification_attempts,
        "notification_sent_at": event.notification_sent_at.isoformat() if event.notification_sent_at else None,
        "notification_error": event.notification_error,
        "notification_results": event.notification_results,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


_SYNC_ALERT_CRITICAL_TYPES = {"DELIVERY_SYNC_FAILED", "RISK_REDIS_UNAVAILABLE"}


def _sync_alert_risk_level(alert_type: str) -> str:
    return "critical" if alert_type in _SYNC_ALERT_CRITICAL_TYPES else "high"


def _sync_alert_to_dict(alert: SyncAlert) -> dict:
    """将同步告警适配为风控事件结构，保证工作台告警可在风控中心闭环处理。"""
    return {
        "id": alert.id,
        "source": "SYNC_ALERT",
        "ad_account_id": alert.ad_account_id,
        "event_type": alert.alert_type,
        "risk_level": _sync_alert_risk_level(alert.alert_type),
        "risk_score": None,
        "title": alert.title,
        "description": alert.message,
        "related_campaign_id": None,
        "related_ad_id": None,
        "is_resolved": bool(alert.is_resolved),
        "resolution": None,
        "resolved_by": None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "auto_action_taken": None,
        "requires_manual_review": True,
        "notification_status": "PENDING",
        "notification_attempts": 0,
        "notification_sent_at": None,
        "notification_error": None,
        "notification_results": None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "updated_at": alert.created_at.isoformat() if alert.created_at else None,
    }


def _rule_to_dict(rule: RiskRule) -> dict:
    data = rule.to_config()
    data.update({
        "tenant_id": rule.tenant_id,
        "is_builtin": rule.tenant_id is None,
        "action_on_trigger": rule.action_on_trigger,
        "alert_channels": rule.alert_channels,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    })
    return data


def _rule_window_days(rule: RiskRule, requested: int = 1) -> int:
    """取 dry-run 的统一指标窗口；条件可通过 window/window_days 提高窗口。"""
    windows = [int(requested or 1)]
    for condition in rule.conditions or []:
        if isinstance(condition, dict):
            value = condition.get("window_days", condition.get("window"))
            try:
                if value is not None:
                    windows.append(int(value))
            except (TypeError, ValueError):
                continue
    return max(1, min(max(windows), 90))


@router.get("/overview")
def risk_overview(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """返回当前用户账户范围内的风控总览指标。"""
    accounts = _visible_account_query(db, current_user).all()
    account_ids = [account.id for account in accounts]

    unresolved_query = db.query(
        RiskEvent.ad_account_id,
        RiskEvent.risk_level,
        func.count(RiskEvent.id),
    ).filter(RiskEvent.is_resolved.is_(False))
    if account_ids:
        unresolved_query = unresolved_query.filter(RiskEvent.ad_account_id.in_(account_ids))
    else:
        unresolved_query = unresolved_query.filter(False)
    unresolved_rows = unresolved_query.group_by(
        RiskEvent.ad_account_id, RiskEvent.risk_level
    ).all()

    unresolved_total = 0
    critical_accounts = set()
    warning_accounts = set()
    for account_id, level, count in unresolved_rows:
        unresolved_total += count
        level_value = level.value if hasattr(level, "value") else str(level).lower()
        if level_value == "critical":
            critical_accounts.add(account_id)
        elif level_value in {"high", "medium"}:
            warning_accounts.add(account_id)

    status_counts = {"normal": 0, "warning": 0, "danger": 0}
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for account in accounts:
        score = float(account.risk_score or 0)
        level = _risk_level(score, int(account.id in critical_accounts))
        risk_counts[level] += 1
        if (
            account.system_status != "ACTIVE"
            or (account.account_status and str(account.account_status).upper() != "ACTIVE")
            or account.id in critical_accounts
        ):
            status_counts["danger"] += 1
        elif account.id in warning_accounts or account.last_sync_error:
            status_counts["warning"] += 1
        else:
            status_counts["normal"] += 1

    today = datetime.utcnow().date()
    executions_query = db.query(RiskExecution).filter(
        RiskExecution.created_at >= datetime.combine(today, datetime.min.time())
    )
    if account_ids:
        executions_query = executions_query.filter(RiskExecution.ad_account_id.in_(account_ids))
    else:
        executions_query = executions_query.filter(False)
    execution_rows = executions_query.all()

    return {
        "scope": {"account_count": len(accounts), "account_ids": account_ids},
        "account_status": status_counts,
        "risk_levels": risk_counts,
        "risk_score": {
            "max": round(max((float(a.risk_score or 0) for a in accounts), default=0), 4),
            "average": round(
                sum(float(a.risk_score or 0) for a in accounts) / len(accounts), 4
            ) if accounts else 0,
        },
        "unresolved_events": unresolved_total,
        "today_executions": len(execution_rows),
        "today_paused": sum(
            1 for item in execution_rows
            if item.action.upper() in {"PAUSE", "PAUSE_CAMPAIGN", "PAUSE_ADSET", "PAUSE_AD"}
            and item.status.upper() in {"SUCCESS", "SUCCEEDED"}
        ),
        "checked_at": datetime.utcnow().isoformat(),
    }


@router.get("/accounts")
def risk_accounts(
    risk_level: Optional[str] = Query(default=None),
    system_status: Optional[str] = Query(default=None),
    unresolved_only: bool = Query(default=False),
    keyword: Optional[str] = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = _visible_account_query(db, current_user)
    if system_status:
        query = query.filter(AdAccount.system_status == system_status)
    if keyword:
        query = query.filter(
            or_(AdAccount.account_name.ilike(f"%{keyword}%"), AdAccount.account_id.ilike(f"%{keyword}%"))
        )

    accounts = query.order_by(AdAccount.updated_at.desc(), AdAccount.id.desc()).all()
    account_ids = [account.id for account in accounts]
    unresolved_rows = {}
    if account_ids:
        rows = db.query(
            RiskEvent.ad_account_id,
            func.count(RiskEvent.id),
            func.max(RiskEvent.created_at),
        ).filter(
            RiskEvent.ad_account_id.in_(account_ids),
            RiskEvent.is_resolved.is_(False),
        ).group_by(RiskEvent.ad_account_id).all()
        unresolved_rows = {row[0]: {"count": row[1], "latest_at": row[2]} for row in rows}

    items = []
    for account in accounts:
        unresolved = unresolved_rows.get(account.id, {"count": 0, "latest_at": None})
        level = _risk_level(float(account.risk_score or 0))
        if risk_level and level != risk_level.lower():
            continue
        if unresolved_only and unresolved["count"] == 0:
            continue
        items.append({
            "id": account.id,
            "account_id": account.account_id,
            "account_name": account.account_name,
            "business_id": account.business_id,
            "system_status": account.system_status,
            "account_status": account.account_status,
            "risk_score": float(account.risk_score or 0),
            "risk_level": level,
            "unresolved_events": unresolved["count"],
            "latest_event_at": unresolved["latest_at"].isoformat() if unresolved["latest_at"] else None,
            "last_risk_check": account.last_risk_check.isoformat() if account.last_risk_check else None,
            "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
            "last_sync_error": account.last_sync_error,
        })

    total = len(items)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], **_page_meta(total, page, page_size)}


@router.post("/accounts/{account_id}/recheck")
def recheck_risk_account(
    account_id: str,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """手动重新检查账户；仍由 Worker 执行，不在 HTTP 线程调用 Meta。"""
    _require_rule_manager(current_user)
    account = _get_visible_account(db, account_id, current_user)
    from tasks.celery_tasks import check_account_risk

    async_result = check_account_risk.delay(account.id)
    record_audit(
        db,
        action="RECHECK_RISK_ACCOUNT",
        resource_type="ad_account",
        resource_id=account.id,
        user_id=current_user.id,
        request_data={"account_id": account_id},
        response_data={"task_id": async_result.id},
        request=request,
    )
    return {"status": "queued", "account_id": account.id, "task_id": async_result.id}


@router.get("/events")
def list_risk_events(
    account_id: Optional[str] = Query(default=None),
    risk_level: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    resolved: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    risk_query = db.query(RiskEvent)
    sync_query = db.query(SyncAlert)
    visible = accessible_account_ids(db, current_user)
    if visible is not None:
        account_ids = visible or {"__none__"}
        risk_query = risk_query.filter(RiskEvent.ad_account_id.in_(account_ids))
        sync_query = sync_query.filter(SyncAlert.ad_account_id.in_(account_ids))
    if account_id:
        account = _get_visible_account(db, account_id, current_user)
        risk_query = risk_query.filter(RiskEvent.ad_account_id == account.id)
        sync_query = sync_query.filter(SyncAlert.ad_account_id == account.id)
    if risk_level:
        try:
            level = RiskLevel(risk_level.lower())
            risk_query = risk_query.filter(RiskEvent.risk_level == level)
            if level == RiskLevel.CRITICAL:
                sync_query = sync_query.filter(SyncAlert.alert_type.in_(_SYNC_ALERT_CRITICAL_TYPES))
            elif level == RiskLevel.HIGH:
                sync_query = sync_query.filter(~SyncAlert.alert_type.in_(_SYNC_ALERT_CRITICAL_TYPES))
            else:
                sync_query = sync_query.filter(False)
        except ValueError:
            raise HTTPException(status_code=422, detail="非法风险等级")
    if event_type:
        try:
            risk_query = risk_query.filter(RiskEvent.event_type == RiskEventType(event_type.lower()))
            sync_query = sync_query.filter(False)
        except ValueError:
            # 同步告警使用独立的字符串类型，例如 DELIVERY_SYNC。
            sync_query = sync_query.filter(SyncAlert.alert_type == event_type.upper())
            risk_query = risk_query.filter(False)
    if resolved is not None:
        risk_query = risk_query.filter(RiskEvent.is_resolved.is_(resolved))
        sync_query = sync_query.filter(SyncAlert.is_resolved.is_(resolved))

    total = risk_query.count() + sync_query.count()
    # 两类数据分别取到当前页所需的最大数量，再按发生时间合并，避免同步告警被
    # 单独分页后挤出风控事件列表。
    fetch_size = page * page_size
    risk_events = risk_query.order_by(RiskEvent.created_at.desc()).limit(fetch_size).all()
    sync_alerts = sync_query.order_by(SyncAlert.created_at.desc()).limit(fetch_size).all()
    merged = [
        (item.created_at or datetime.min, _event_to_dict(item)) for item in risk_events
    ] + [
        (item.created_at or datetime.min, _sync_alert_to_dict(item)) for item in sync_alerts
    ]
    merged.sort(key=lambda item: item[0], reverse=True)
    start = (page - 1) * page_size
    return {
        "items": [item[1] for item in merged[start:start + page_size]],
        **_page_meta(total, page, page_size),
    }


def _get_event(db: Session, event_id: str, current_user: User) -> RiskEvent:
    event = db.query(RiskEvent).filter(RiskEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="风险事件不存在")
    _get_visible_account(db, event.ad_account_id, current_user)
    return event


def _get_sync_alert(db: Session, alert_id: str, current_user: User) -> SyncAlert:
    query = db.query(SyncAlert).filter(SyncAlert.id == alert_id)
    visible = accessible_account_ids(db, current_user)
    if visible is not None:
        query = query.filter(SyncAlert.ad_account_id.in_(visible or {"__none__"}))
    alert = query.first()
    if not alert:
        raise HTTPException(status_code=404, detail="风险事件不存在")
    return alert


@router.get("/events/{event_id}")
def get_risk_event(
    event_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    event = db.query(RiskEvent).filter(RiskEvent.id == event_id).first()
    if event:
        _get_visible_account(db, event.ad_account_id, current_user)
        return _event_to_dict(event)
    return _sync_alert_to_dict(_get_sync_alert(db, event_id, current_user))


@router.post("/events/{event_id}/resolve")
def resolve_risk_event(
    event_id: str,
    payload: RiskEventResolvePayload,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    event = db.query(RiskEvent).filter(RiskEvent.id == event_id).first()
    if event:
        _get_visible_account(db, event.ad_account_id, current_user)
        event.is_resolved = True
        event.resolution = payload.resolution.strip()
        event.resolved_by = current_user.id
        event.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(event)
        record_audit(
            db,
            action="RESOLVE_RISK_EVENT",
            resource_type="risk_event",
            resource_id=event.id,
            user_id=current_user.id,
            request_data=payload.model_dump(),
            response_data={"resolved": True},
            request=request,
        )
        return _event_to_dict(event)

    alert = _get_sync_alert(db, event_id, current_user)
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)
    record_audit(
        db,
        action="RESOLVE_SYNC_ALERT",
        resource_type="sync_alert",
        resource_id=alert.id,
        user_id=current_user.id,
        request_data=payload.model_dump(),
        response_data={"resolved": True},
        request=request,
    )
    return _sync_alert_to_dict(alert)


@router.get("/rules")
def list_risk_rules(
    active_only: bool = Query(default=False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(RiskRule)
    if active_only:
        query = query.filter(RiskRule.is_active.is_(True))
    rules = query.order_by(RiskRule.priority.desc(), RiskRule.created_at.asc()).all()
    return {"items": [_rule_to_dict(rule) for rule in rules]}


def _get_rule(db: Session, rule_id: str) -> RiskRule:
    rule = db.query(RiskRule).filter(RiskRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="风控规则不存在")
    return rule


def _apply_rule_payload(rule: RiskRule, payload: RiskRulePayload) -> None:
    data = payload.model_dump()
    data["logic"] = data["logic"].upper()
    for field in ("scope", "conditions", "whitelist"):
        setattr(rule, field, data[field])
    for field in (
        "name", "description", "rule_type", "is_active", "logic", "threshold",
        "threshold_unit", "min_spend", "min_runtime", "cooldown_seconds",
        "max_actions_per_run", "dry_run", "action_on_trigger", "alert_channels", "priority",
    ):
        setattr(rule, field, data[field])


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_risk_rule(
    payload: RiskRulePayload,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_rule_manager(current_user)
    tenant_id = effective_tenant_id(current_user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="平台账号请先切换到具体租户")
    duplicate = db.query(RiskRule).filter(
        RiskRule.tenant_id == tenant_id,
        RiskRule.name == payload.name.strip(),
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="租户内已存在同名风控规则")

    rule = RiskRule(id=uuid.uuid4().hex, tenant_id=tenant_id, name=payload.name.strip(), rule_type=payload.rule_type)
    _apply_rule_payload(rule, payload)
    db.add(rule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="风控规则名称冲突")
    db.refresh(rule)
    record_audit(
        db,
        action="CREATE_RISK_RULE",
        resource_type="risk_rule",
        resource_id=rule.id,
        user_id=current_user.id,
        request_data=payload.model_dump(),
        response_data={"version": rule.version},
        request=request,
    )
    return _rule_to_dict(rule)


@router.put("/rules/{rule_id}")
def update_risk_rule(
    rule_id: str,
    payload: RiskRulePayload,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_rule_manager(current_user)
    rule = _get_rule(db, rule_id)
    if rule.tenant_id is None:
        raise HTTPException(status_code=403, detail="平台内置规则不可修改")
    if rule.tenant_id != effective_tenant_id(current_user):
        raise HTTPException(status_code=403, detail="无权修改该风控规则")
    _apply_rule_payload(rule, payload)
    rule.version = int(rule.version or 1) + 1
    db.commit()
    db.refresh(rule)
    record_audit(
        db,
        action="UPDATE_RISK_RULE",
        resource_type="risk_rule",
        resource_id=rule.id,
        user_id=current_user.id,
        request_data=payload.model_dump(),
        response_data={"version": rule.version},
        request=request,
    )
    return _rule_to_dict(rule)


@router.post("/rules/{rule_id}/toggle")
def toggle_risk_rule(
    rule_id: str,
    payload: RiskRuleTogglePayload,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_rule_manager(current_user)
    rule = _get_rule(db, rule_id)
    if rule.tenant_id is None:
        raise HTTPException(status_code=403, detail="平台内置规则不可修改")
    if rule.tenant_id != effective_tenant_id(current_user):
        raise HTTPException(status_code=403, detail="无权修改该风控规则")
    rule.is_active = payload.is_active
    rule.version = int(rule.version or 1) + 1
    db.commit()
    db.refresh(rule)
    record_audit(
        db,
        action="TOGGLE_RISK_RULE",
        resource_type="risk_rule",
        resource_id=rule.id,
        user_id=current_user.id,
        request_data=payload.model_dump(),
        response_data={"is_active": rule.is_active, "version": rule.version},
        request=request,
    )
    return _rule_to_dict(rule)


@router.post("/rules/{rule_id}/dry-run")
def dry_run_risk_rule(
    rule_id: str,
    payload: RiskRuleDryRunPayload,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_rule_manager(current_user)
    rule = _get_rule(db, rule_id)
    query = _visible_account_query(db, current_user)
    if payload.account_ids:
        accounts = query.filter(AdAccount.id.in_(payload.account_ids)).all()
        if len(accounts) != len(set(payload.account_ids)):
            raise HTTPException(status_code=403, detail="dry-run 包含不可访问的广告账户")
    else:
        accounts = query.order_by(AdAccount.id.asc()).limit(100).all()

    engine = RiskRuleEngine(db)
    now = datetime.utcnow()
    targets = []
    conditions_evaluated = 0
    matched_count = 0
    skipped_count = 0
    window_days = _rule_window_days(rule, payload.window_days)
    for account in accounts:
        for target_type, target_id in rule_targets(db, account, rule):
            metrics = load_target_metrics(
                db, account, target_type, target_id, window_days=window_days, as_of=now.date()
            )
            runtime_seconds = max(0, int((now - account.created_at).total_seconds())) if account.created_at else 0
            evaluation = engine.evaluate(
                rule,
                account.id,
                target_type=target_type,
                target_id=target_id,
                metrics=metrics,
                runtime_seconds=runtime_seconds,
                window_key=now.date().isoformat(),
                now=now,
            )
            conditions_evaluated += len(evaluation["conditions"])
            if evaluation["matched"]:
                matched_count += 1
            else:
                skipped_count += 1
            targets.append({
                "ad_account_id": account.id,
                "account_id": account.account_id,
                "account_name": account.account_name,
                "target_type": target_type,
                "target_id": target_id,
                "metrics": metrics,
                "evaluation": evaluation,
            })

    preview = {
        "status": "preview_only",
        "will_call_meta": False,
        "rule": _rule_to_dict(rule),
        "targets": targets,
        "conditions_evaluated": conditions_evaluated,
        "matched_count": matched_count,
        "skipped_count": skipped_count,
        "window_days": window_days,
        "message": "规则已基于本地 Insights 完成只读评估；当前阶段不会创建执行记录或调用 Meta 写接口。",
    }
    record_audit(
        db,
        action="DRY_RUN_RISK_RULE",
        resource_type="risk_rule",
        resource_id=rule.id,
        user_id=current_user.id,
        request_data=payload.model_dump(),
        response_data={"target_count": len(accounts), "will_call_meta": False},
        request=request,
    )
    return preview


@router.get("/executions")
def list_risk_executions(
    account_id: Optional[str] = Query(default=None),
    rule_id: Optional[str] = Query(default=None),
    execution_status: Optional[str] = Query(default=None, alias="status"),
    mode: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = db.query(RiskExecution)
    visible = accessible_account_ids(db, current_user)
    if visible is not None:
        query = query.filter(RiskExecution.ad_account_id.in_(visible or ["__none__"]))
    if account_id:
        account = _get_visible_account(db, account_id, current_user)
        query = query.filter(RiskExecution.ad_account_id == account.id)
    if rule_id:
        query = query.filter(RiskExecution.rule_id == rule_id)
    if execution_status:
        query = query.filter(RiskExecution.status == execution_status.upper())
    if mode:
        query = query.filter(RiskExecution.mode == mode.upper())

    total = query.count()
    records = query.order_by(RiskExecution.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [item.to_dict() for item in records], **_page_meta(total, page, page_size)}


@router.get("/executions/{execution_id}")
def get_risk_execution(
    execution_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    record = db.query(RiskExecution).filter(RiskExecution.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="风控执行记录不存在")
    _get_visible_account(db, record.ad_account_id, current_user)
    return record.to_dict()


@router.post("/executions/{execution_id}/retry")
def retry_risk_execution(
    execution_id: str,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _require_rule_manager(current_user)
    record = db.query(RiskExecution).filter(RiskExecution.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="风控执行记录不存在")
    _get_visible_account(db, record.ad_account_id, current_user)
    if record.status != "FAILED":
        raise HTTPException(status_code=409, detail="仅 FAILED 执行记录允许重试")
    from tasks.celery_tasks import retry_risk_execution as retry_task

    async_result = retry_task.delay(record.id)
    record_audit(
        db,
        action="RETRY_RISK_EXECUTION",
        resource_type="risk_execution",
        resource_id=record.id,
        user_id=current_user.id,
        request_data={"execution_id": execution_id},
        response_data={"task_id": async_result.id},
        request=request,
    )
    return {"status": "queued", "execution_id": record.id, "task_id": async_result.id}
