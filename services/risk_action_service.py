"""RC-04 风控动作服务。

动作执行遵循：规则重新评估 → 目标状态二次校验 → DeliveryAction 幂等记录
→ Meta Connector 写操作 → 本地状态同步 → RiskExecution 完成记录。
本模块不允许通过修改本地状态伪造 Meta 暂停结果。
"""

from __future__ import annotations

import uuid
import hashlib
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import settings
from core.logger import logger
from models import (
    Ad,
    AdAccount,
    AdGroup,
    Campaign,
    CampaignStatus,
    DeliveryAction,
    RiskEvent,
    RiskEventType,
    RiskExecution,
    RiskLevel,
    RiskRule,
    SystemStatus,
)
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient
from services.risk_reliability import classify_risk_error
from services.risk_rule_engine import RiskRuleEngine, kill_switch_enabled, load_target_metrics


LIVE_ACTIONS = {"PAUSE_CAMPAIGN", "PAUSE_ADSET", "PAUSE_AD", "FREEZE_ACCOUNT", "ALERT"}


def _now() -> datetime:
    return datetime.utcnow()


def _normal_action(value: Optional[str]) -> str:
    action = str(value or "ALERT").strip().upper().replace("-", "_")
    aliases = {"PAUSE": "PAUSE_CAMPAIGN", "FREEZE": "FREEZE_ACCOUNT", "NOTIFY": "ALERT"}
    return aliases.get(action, action)


def _safe_response(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    return {"value": str(value)[:1000]}


def _child_idempotency_key(parent_key: str, object_type: str, remote_id: str) -> str:
    raw = f"{parent_key}|{object_type.upper()}|{remote_id}"
    return f"risk-action:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


class RiskActionService:
    def __init__(self, db: Session):
        self.db = db

    def _find_execution(self, key: str) -> Optional[RiskExecution]:
        return self.db.query(RiskExecution).filter(RiskExecution.idempotency_key == key).first()

    def _upsert_execution(
        self,
        rule: RiskRule,
        account: AdAccount,
        evaluation: dict,
        metrics: dict,
        run_id: str,
    ) -> RiskExecution:
        key = evaluation["idempotency_key"]
        execution = self._find_execution(key)
        if execution is None:
            execution = RiskExecution(
                id=uuid.uuid4().hex,
                tenant_id=account.tenant_id,
                run_id=run_id,
                rule_id=rule.id,
                ad_account_id=account.id,
                target_type=str(evaluation.get("target_type") or "ACCOUNT").upper(),
                target_id=str(evaluation.get("target_id") or account.id),
                rule_version=int(rule.version or 1),
                mode="DRY_RUN" if rule.dry_run else "LIVE",
                status="RUNNING",
                action=_normal_action(rule.action_on_trigger),
                matched_conditions=evaluation.get("conditions") or [],
                metrics_snapshot=metrics,
                idempotency_key=key,
                started_at=_now(),
            )
            self.db.add(execution)
        else:
            if execution.status == "SUCCESS":
                return execution
            execution.run_id = run_id
            execution.mode = "DRY_RUN" if rule.dry_run else "LIVE"
            execution.status = "RUNNING"
            execution.action = _normal_action(rule.action_on_trigger)
            execution.matched_conditions = evaluation.get("conditions") or []
            execution.metrics_snapshot = metrics
            execution.started_at = _now()
            execution.error_code = None
            execution.error_message = None
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self._find_execution(key)
            if existing is None:
                raise
            return existing
        self.db.refresh(execution)
        return execution

    def record_skipped(
        self,
        rule: RiskRule,
        account: AdAccount,
        evaluation: dict,
        metrics: dict,
        run_id: str,
    ) -> RiskExecution:
        """记录安全护栏跳过结果；不会把未命中条件写成 cooldown 依据。"""
        key = evaluation["idempotency_key"]
        execution = self._find_execution(key)
        if execution is None:
            execution = RiskExecution(
                id=uuid.uuid4().hex,
                tenant_id=account.tenant_id,
                run_id=run_id,
                rule_id=rule.id,
                ad_account_id=account.id,
                target_type=str(evaluation.get("target_type") or "ACCOUNT").upper(),
                target_id=str(evaluation.get("target_id") or account.id),
                rule_version=int(rule.version or 1),
                mode="DRY_RUN" if rule.dry_run else "LIVE",
                status="SKIPPED",
                action=_normal_action(rule.action_on_trigger),
                matched_conditions=evaluation.get("conditions") or [],
                metrics_snapshot=metrics,
                idempotency_key=key,
                provider_response={"reason": evaluation.get("reason")},
                finished_at=_now(),
            )
            self.db.add(execution)
        elif execution.status != "SUCCESS":
            execution.status = "SKIPPED"
            execution.provider_response = {"reason": evaluation.get("reason")}
            execution.metrics_snapshot = metrics
            execution.finished_at = _now()
        self.db.commit()
        return execution

    def _create_delivery_action(self, account: AdAccount, object_type: str, object_id: str, key: str, before_status: str) -> DeliveryAction:
        action = self.db.query(DeliveryAction).filter(DeliveryAction.idempotency_key == key).first()
        if action:
            return action
        action = DeliveryAction(
            id=uuid.uuid4().hex,
            tenant_id=account.tenant_id,
            object_type=object_type,
            object_id=object_id,
            account_id=account.id,
            action="PAUSE",
            requested_by="risk-engine",
            status="REQUESTED",
            idempotency_key=key,
            before_status=before_status,
            desired_status="PAUSED",
        )
        self.db.add(action)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(DeliveryAction).filter(DeliveryAction.idempotency_key == key).first()
            if existing is None:
                raise
            return existing
        return action

    def _pause_remote(self, account: AdAccount, object_type: str, object_id: str, remote_id: str, local_object: Any, key: str) -> dict:
        before_status = str(getattr(local_object, "status", "UNKNOWN"))
        action = self._create_delivery_action(account, object_type, object_id, key, before_status)
        if action.status == "SUCCESS":
            return {"status": "success", "object_type": object_type, "object_id": object_id, "idempotent": True}
        action_id = action.id
        action.status = "RUNNING"
        action.started_at = _now()
        self.db.commit()
        try:
            ref = CredentialResolver(self.db).for_account(account.id)
            if object_type == "CAMPAIGN":
                response = FBConnectorClient().pause_campaign(
                    remote_id,
                    ref.credential_id,
                    idempotency_key=key,
                )
            else:
                response = FBConnectorClient().update_object(
                    object_type,
                    remote_id,
                    ref.credential_id,
                    {"status": "PAUSED"},
                    idempotency_key=key,
                )
            if object_type == "CAMPAIGN":
                local_object.status = CampaignStatus.PAUSED
            else:
                local_object.status = "PAUSED"
            action.status = "SUCCESS"
            action.remote_status = "PAUSED"
            action.result_payload = _safe_response(response)
            action.finished_at = _now()
            self.db.commit()
            return {"status": "success", "object_type": object_type, "object_id": object_id, "provider_response": _safe_response(response)}
        except Exception as exc:
            action = self.db.query(DeliveryAction).filter(DeliveryAction.id == action_id).first()
            if action:
                action.status = "FAILED"
                action.error_message = str(exc)[:1000]
                action.finished_at = _now()
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()
            raise

    def _active_campaigns(self, account_id: str) -> list[Campaign]:
        return self.db.query(Campaign).filter(
            Campaign.ad_account_id == account_id,
            Campaign.status == CampaignStatus.ACTIVE,
        ).order_by(Campaign.id.asc()).all()

    def _target_objects(self, account: AdAccount, target_type: str, target_id: str, action: str) -> list[tuple[str, str, str, Any]]:
        target_type = target_type.upper()
        if target_type == "ACCOUNT":
            if action == "PAUSE_CAMPAIGN":
                return [("CAMPAIGN", campaign.id, campaign.campaign_id, campaign) for campaign in self._active_campaigns(account.id)]
            if action == "PAUSE_ADSET":
                groups = self.db.query(AdGroup).join(Campaign).filter(
                    Campaign.ad_account_id == account.id,
                    AdGroup.status == "ACTIVE",
                ).order_by(AdGroup.id.asc()).all()
                return [("ADSET", group.id, group.ad_group_id, group) for group in groups]
            if action == "PAUSE_AD":
                ads = self.db.query(Ad).join(AdGroup).join(Campaign).filter(
                    Campaign.ad_account_id == account.id,
                    Ad.status == "ACTIVE",
                ).order_by(Ad.id.asc()).all()
                return [("AD", ad.id, ad.ad_id, ad) for ad in ads]
            return []
        if target_type == "CAMPAIGN":
            campaign = self.db.query(Campaign).filter(
                Campaign.ad_account_id == account.id,
                or_(Campaign.id == target_id, Campaign.campaign_id == target_id),
            ).first()
            return [("CAMPAIGN", campaign.id, campaign.campaign_id, campaign)] if campaign and campaign.status == CampaignStatus.ACTIVE else []
        if target_type == "ADSET":
            group = self.db.query(AdGroup).join(Campaign).filter(
                Campaign.ad_account_id == account.id,
                or_(AdGroup.id == target_id, AdGroup.ad_group_id == target_id),
            ).first()
            return [("ADSET", group.id, group.ad_group_id, group)] if group and str(group.status).upper() == "ACTIVE" else []
        if target_type == "AD":
            ad = self.db.query(Ad).join(AdGroup).join(Campaign).filter(
                Campaign.ad_account_id == account.id,
                or_(Ad.id == target_id, Ad.ad_id == target_id),
            ).first()
            return [("AD", ad.id, ad.ad_id, ad)] if ad and str(ad.status).upper() == "ACTIVE" else []
        return []

    def _freeze_account(self, account: AdAccount, rule: RiskRule, metrics: dict) -> dict:
        if account.system_status != SystemStatus.DISABLED.value:
            account.system_status = SystemStatus.DISABLED.value
            account.system_status_reason = f"风控规则命中：{rule.name}"
            account.system_status_at = _now()
        self.db.commit()
        return {"status": "success", "action": "FREEZE_ACCOUNT", "account_id": account.id, "state": "DISABLED"}

    def _create_event(self, account: AdAccount, rule: RiskRule, evaluation: dict, metrics: dict) -> Optional[RiskEvent]:
        title = f"规则命中：{rule.name}"
        existing = self.db.query(RiskEvent).filter(
            RiskEvent.ad_account_id == account.id,
            RiskEvent.title == title,
            RiskEvent.is_resolved.is_(False),
        ).first()
        if existing:
            return existing
        event = RiskEvent(
            id=uuid.uuid4().hex,
            tenant_id=account.tenant_id,
            ad_account_id=account.id,
            event_type=RiskEventType.SUSPICIOUS_PATTERN,
            risk_level=RiskLevel.HIGH,
            risk_score=1.0,
            title=title,
            description=f"规则条件已满足，动作：{_normal_action(rule.action_on_trigger)}；指标窗口：{metrics.get('window_days', 1)} 天。",
            auto_action_taken=_normal_action(rule.action_on_trigger),
            requires_manual_review=_normal_action(rule.action_on_trigger) != "ALERT",
        )
        self.db.add(event)
        self.db.commit()
        return event

    def execute(
        self,
        rule: RiskRule,
        account: AdAccount,
        evaluation: dict,
        metrics: dict,
        run_id: str,
        *,
        max_actions: Optional[int] = None,
    ) -> RiskExecution:
        action = _normal_action(rule.action_on_trigger)
        if rule.dry_run:
            evaluation = {**evaluation, "matched": False, "reason": "DRY_RUN"}
            return self.record_skipped(rule, account, evaluation, metrics, run_id)
        if kill_switch_enabled(self.db, rule.tenant_id):
            evaluation = {**evaluation, "matched": False, "reason": "KILL_SWITCH"}
            return self.record_skipped(rule, account, evaluation, metrics, run_id)
        if action not in LIVE_ACTIONS:
            evaluation = {**evaluation, "matched": False, "reason": "UNSUPPORTED_ACTION"}
            return self.record_skipped(rule, account, evaluation, metrics, run_id)

        execution = self._upsert_execution(rule, account, evaluation, metrics, run_id)
        if execution.status == "SUCCESS":
            return execution
        execution_id = execution.id
        execution_snapshot = {
            "tenant_id": account.tenant_id,
            "run_id": run_id,
            "rule_id": rule.id,
            "ad_account_id": account.id,
            "target_type": str(evaluation.get("target_type") or "ACCOUNT").upper(),
            "target_id": str(evaluation.get("target_id") or account.id),
            "rule_version": int(rule.version or 1),
            "action": action,
            "matched_conditions": evaluation.get("conditions") or [],
            "metrics_snapshot": metrics,
            "idempotency_key": evaluation["idempotency_key"],
        }
        try:
            if action == "FREEZE_ACCOUNT":
                provider = self._freeze_account(account, rule, metrics)
            elif action == "ALERT":
                provider = {"status": "success", "action": "ALERT", "meta_called": False}
                self.db.commit()
            else:
                objects = self._target_objects(
                    account,
                    evaluation.get("target_type", "ACCOUNT"),
                    evaluation.get("target_id", account.id),
                    action,
                )
                if max_actions is not None:
                    objects = objects[:max(0, int(max_actions))]
                results = []
                for object_type, object_id, remote_id, local_object in objects:
                    child_key = _child_idempotency_key(evaluation["idempotency_key"], object_type, remote_id)
                    results.append(self._pause_remote(account, object_type, object_id, remote_id, local_object, child_key))
                provider = {"status": "success", "action": action, "target_count": len(results), "results": results}
            execution.status = "SUCCESS"
            execution.provider_response = provider
            execution.finished_at = _now()
            self.db.commit()
            try:
                self._create_event(account, rule, evaluation, metrics)
            except Exception:
                # 动作已经成功，事件/通知失败不能把 Meta 成功误报为动作失败；
                # 后续告警恢复任务会通过 execution.status 发现该异常。
                self.db.rollback()
                logger.exception("[risk] action succeeded but risk event creation failed rule=%s account=%s", rule.id, account.id)
            return execution
        except Exception as exc:
            try:
                execution = self.db.query(RiskExecution).filter(RiskExecution.id == execution_id).first()
                if execution is None:
                    # 某些数据库/事务代理在外部调用异常后会回滚当前事务，
                    # 此时补写一条 FAILED 记录，不能让“远端失败”变成无记录异常。
                    execution = RiskExecution(id=execution_id, mode="LIVE", status="FAILED", **execution_snapshot)
                    self.db.add(execution)
                execution.status = "FAILED"
                execution.error_code = classify_risk_error(exc)
                execution.error_message = str(exc)[:2000]
                execution.retry_count = int(execution.retry_count or 0) + 1
                execution.finished_at = _now()
                self.db.commit()
            except Exception:
                self.db.rollback()
            logger.exception("[risk] rule action failed rule=%s account=%s", execution_snapshot["rule_id"], execution_snapshot["ad_account_id"])
            return execution


def rule_targets(db: Session, account: AdAccount, rule: RiskRule) -> list[tuple[str, str]]:
    """展开规则 scope，且始终把目标限制在当前账户下。"""
    scope = rule.scope or {}
    level = str(scope.get("level") or scope.get("type") or "ACCOUNT").upper()
    ids = [str(item) for item in (scope.get("ids") or [])]
    if level in {"ACCOUNT", "ALL"}:
        return [("ACCOUNT", account.id)]
    if level == "CAMPAIGN":
        query = db.query(Campaign).filter(
            Campaign.ad_account_id == account.id,
            Campaign.status == CampaignStatus.ACTIVE,
        )
        if ids:
            query = query.filter(or_(Campaign.id.in_(ids), Campaign.campaign_id.in_(ids)))
        return [("CAMPAIGN", item.id) for item in query.order_by(Campaign.id.asc()).all()]
    if level == "ADSET":
        query = db.query(AdGroup).join(Campaign).filter(
            Campaign.ad_account_id == account.id,
            AdGroup.status == "ACTIVE",
        )
        if ids:
            query = query.filter(or_(AdGroup.id.in_(ids), AdGroup.ad_group_id.in_(ids)))
        return [("ADSET", item.id) for item in query.order_by(AdGroup.id.asc()).all()]
    if level == "AD":
        query = db.query(Ad).join(AdGroup).join(Campaign).filter(
            Campaign.ad_account_id == account.id,
            Ad.status == "ACTIVE",
        )
        if ids:
            query = query.filter(or_(Ad.id.in_(ids), Ad.ad_id.in_(ids)))
        return [("AD", item.id) for item in query.order_by(Ad.id.asc()).all()]
    return [("ACCOUNT", account.id)]


def run_account_rules(db: Session, account: AdAccount, *, run_id: Optional[str] = None) -> dict:
    """重新读取本地指标并执行账户级规则。"""
    run_id = run_id or uuid.uuid4().hex
    account_id = account.id
    rules = db.query(RiskRule).filter(RiskRule.is_active.is_(True)).order_by(
        RiskRule.priority.desc(), RiskRule.created_at.asc()
    ).all()
    engine = RiskRuleEngine(db)
    actions_started = 0
    counts = {"matched": 0, "skipped": 0, "not_matched": 0, "success": 0, "failed": 0}
    executions = []
    action_service = RiskActionService(db)
    rule_action_counts: dict[str, int] = {}
    for rule in rules:
        window_days = max([1] + [int(item.get("window_days", item.get("window", 1))) for item in (rule.conditions or []) if isinstance(item, dict) and str(item.get("window_days", item.get("window", 1))).isdigit()])
        for target_type, target_id in rule_targets(db, account, rule):
            metrics = load_target_metrics(db, account, target_type, target_id, window_days=min(window_days, 90))
            runtime = max(0, int((_now() - account.created_at).total_seconds())) if account.created_at else 0
            evaluation = engine.evaluate(
                rule,
                account.id,
                target_type=target_type,
                target_id=target_id,
                metrics=metrics,
                runtime_seconds=runtime,
                window_key=metrics.get("to_date"),
            )
            evaluation["target_type"] = target_type
            evaluation["target_id"] = target_id
            if evaluation["matched"]:
                counts["matched"] += 1
                rule_limit = int(rule.max_actions_per_run or 100)
                used_for_rule = rule_action_counts.get(rule.id, 0)
                if used_for_rule >= rule_limit:
                    evaluation = {**evaluation, "matched": False, "reason": "MAX_ACTIONS_PER_RUN"}
                    record = action_service.record_skipped(rule, account, evaluation, metrics, run_id)
                    counts["skipped"] += 1
                else:
                    record = action_service.execute(
                        rule,
                        account,
                        evaluation,
                        metrics,
                        run_id,
                        max_actions=rule_limit - used_for_rule,
                    )
                    provider = record.provider_response or {}
                    started = int(provider.get("target_count", 1)) if record.status in {"SUCCESS", "FAILED"} else 0
                    rule_action_counts[rule.id] = used_for_rule + max(0, started)
                    actions_started += max(0, started)
                    if record.status == "SUCCESS":
                        counts["success"] += 1
                    elif record.status == "FAILED":
                        counts["failed"] += 1
                    elif record.status == "SKIPPED":
                        counts["skipped"] += 1
            elif evaluation["reason"] == "CONDITIONS_NOT_MATCHED":
                counts["not_matched"] += 1
                continue
            else:
                counts["skipped"] += 1
                record = action_service.record_skipped(rule, account, evaluation, metrics, run_id)
            executions.append(record.id)
    return {"run_id": run_id, "account_id": account_id, "rule_count": len(rules), "actions_started": actions_started, "counts": counts, "execution_ids": executions}


def retry_failed_execution(db: Session, execution: RiskExecution) -> RiskExecution:
    """显式重试失败动作；重新读取指标并再次经过全部安全护栏。"""
    rule = db.query(RiskRule).filter(RiskRule.id == execution.rule_id).first()
    account = db.query(AdAccount).filter(AdAccount.id == execution.ad_account_id).first()
    if not rule or not account:
        execution.status = "FAILED"
        execution.error_code = "TARGET_NOT_FOUND"
        execution.error_message = "规则或广告账户不存在"
        execution.finished_at = _now()
        db.commit()
        return execution

    window_days = max([1] + [int(item.get("window_days", item.get("window", 1))) for item in (rule.conditions or []) if isinstance(item, dict) and str(item.get("window_days", item.get("window", 1))).isdigit()])
    metrics = load_target_metrics(
        db,
        account,
        execution.target_type,
        execution.target_id,
        window_days=min(window_days, 90),
    )
    runtime = max(0, int((_now() - account.created_at).total_seconds())) if account.created_at else 0
    evaluation = RiskRuleEngine(db).evaluate(
        rule,
        account.id,
        target_type=execution.target_type,
        target_id=execution.target_id,
        metrics=metrics,
        runtime_seconds=runtime,
        window_key=metrics.get("to_date"),
    )
    evaluation["target_type"] = execution.target_type
    evaluation["target_id"] = execution.target_id
    service = RiskActionService(db)
    if not evaluation["matched"]:
        return service.record_skipped(rule, account, evaluation, metrics, execution.run_id or uuid.uuid4().hex)
    return service.execute(rule, account, evaluation, metrics, execution.run_id or uuid.uuid4().hex)
