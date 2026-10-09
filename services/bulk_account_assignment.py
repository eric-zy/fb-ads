"""Previewed, account-scoped bulk assignment with atomic audit and replay."""
import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from core.tenant import effective_tenant_id
from models import AdAccount, AuditLog, User, UserAccount
from services.account_operation_lease import AccountOperationLeaseService
from services.meta_execution_access import execution_candidates, WRITE_ACCOUNT_ROLES


class AssignmentContextRequest(BaseModel):
    account_ids: list[str] = Field(min_length=1, max_length=100)


class BulkAssignmentRequest(AssignmentContextRequest):
    action: Literal["COLLABORATOR", "PRIMARY", "EXECUTION"] = "COLLABORATOR"
    user_ids: list[str] = Field(min_length=1, max_length=100)
    primary_user_id: str | None = None
    execution_mode: Literal["KEEP", "PERSONAL", "DELEGATED"] = "KEEP"
    execution_connection_id: str | None = None
    execution_overrides: dict[str, str] = Field(default_factory=dict)
    preserve_existing_execution: bool = True

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "PRIMARY" and self.primary_user_id not in self.user_ids:
            raise ValueError("请选择本次目标用户中的一名负责人")
        if self.action == "EXECUTION" and self.execution_mode == "KEEP":
            raise ValueError("批量设置执行授权需选择本人授权或管理员委派")
        if set(self.execution_overrides) - set(self.account_ids):
            raise ValueError("授权例外只能配置本次选择的账户")
        return self


class BulkAssignmentSubmit(BulkAssignmentRequest):
    idempotency_key: str = Field(min_length=16, max_length=100)
    preview_hashes: dict[str, str]


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _signature(request, account_id):
    return {"action": request.action, "user_ids": sorted(set(request.user_ids)),
        "primary_user_id": request.primary_user_id, "execution_mode": request.execution_mode,
        "execution_connection_id": request.execution_overrides.get(account_id, request.execution_connection_id),
        "preserve_existing_execution": request.preserve_existing_execution}


def _effective(row):
    return row.assignment_status == "ACTIVE" and (not row.expires_at or row.expires_at > datetime.utcnow())


def _rows(db, account):
    return db.query(UserAccount).filter_by(tenant_id=account.tenant_id, account_id=account.id).order_by(UserAccount.user_id).all()


def _state(rows):
    return [{"user_id": x.user_id, "role": x.role, "assignment_role": x.assignment_role,
        "assignment_status": x.assignment_status, "expires_at": x.expires_at,
        "execution_connection_id": x.execution_connection_id, "execution_granted_at": x.execution_granted_at,
        "effective": _effective(x)} for x in rows]


def _account(db, actor, account_id, lock=False):
    q = db.query(AdAccount).filter_by(id=account_id)
    tenant_id = effective_tenant_id(actor)
    if not tenant_id:
        raise HTTPException(400, "请先切换到目标租户后批量分配")
    q = q.filter_by(tenant_id=tenant_id)
    account = (q.with_for_update() if lock else q).first()
    if not account:
        raise HTTPException(404, "账户不存在或不属于当前租户")
    return account


def assignment_context(db, actor, request):
    tenant_id = effective_tenant_id(actor)
    if not tenant_id:
        raise HTTPException(400, "请先切换到目标租户后批量分配")
    users = db.query(User).filter_by(tenant_id=tenant_id, is_active=True).order_by(User.username).all()
    names = {u.id: u.username for u in db.query(User).filter_by(tenant_id=tenant_id).all()}
    items = []
    for key in dict.fromkeys(request.account_ids):
        try:
            account = _account(db, actor, key)
            rows = _rows(db, account)
            items.append({"account_id": key, "account_name": account.account_name or account.account_id,
                "assignments": [{**x, "username": names.get(x["user_id"], "用户已删除")} for x in _state(rows)],
                "candidates": execution_candidates(db, account), "error": None})
        except HTTPException as exc:
            items.append({"account_id": key, "account_name": key, "assignments": [], "candidates": [], "error": exc.detail})
    return {"items": items, "users": [{"id": u.id, "username": u.username} for u in users]}


def preview_account(db, actor, request, account):
    signature = _signature(request, account.id)
    users = db.query(User).filter(User.id.in_(signature["user_ids"]), User.tenant_id == account.tenant_id, User.is_active.is_(True)).all()
    if len(users) != len(signature["user_ids"]):
        raise HTTPException(400, "目标用户不存在、已停用或不属于当前租户")
    names = {u.id: u.username for u in db.query(User).filter_by(tenant_id=account.tenant_id).all()}
    rows = _rows(db, account)
    by_user = {r.user_id: r for r in rows}
    candidates = sorted(execution_candidates(db, account), key=lambda c: c["connection_id"])
    choices = {c["connection_id"]: c for c in candidates}
    old_primary = next((r.user_id for r in rows if _effective(r) and r.assignment_role == "PRIMARY"), None)
    primary = request.primary_user_id if request.action == "PRIMARY" else old_primary
    if not primary and request.action != "EXECUTION":
        primary = signature["user_ids"][0]
    assignments = []
    warnings = []
    for uid in signature["user_ids"]:
        row = by_user.get(uid)
        active = bool(row and _effective(row))
        if request.action == "EXECUTION" and (not active or row.role not in WRITE_ACCOUNT_ROLES):
            raise HTTPException(400, f"{names[uid]} 尚未获得此账户的有效操作分配，请先添加协作者")
        existing = row.execution_connection_id if active else None
        if request.execution_mode == "KEEP":
            connection_id = existing
        elif request.execution_mode == "PERSONAL":
            connection_id = None
        else:
            connection_id = existing if request.preserve_existing_execution and existing in choices else signature["execution_connection_id"]
            if not connection_id or connection_id not in choices:
                raise HTTPException(400, "请为此账户选择有效的委派执行授权")
        source = choices.get(connection_id)
        if connection_id and not source:
            warnings.append(f"{names[uid]} 的已有委派授权失效，保留分配但不可执行")
        elif source and source["page_count"] == 0:
            warnings.append(f"{names[uid]} 的执行授权没有可投放 Page，暂不可新建广告")
        elif not connection_id:
            warnings.append(f"{names[uid]} 使用本人 Meta 授权，投放前需校验个人授权及 Page")
        assignments.append({"user_id": uid, "username": names[uid], "execution_connection_id": connection_id,
            "execution_label": f'{source["authorized_by_username"]} · Meta {source["meta_user_id"]}' if source else "已有委派失效" if connection_id else "本人 Meta 授权"})
    return {"account_id": account.id, "account_name": account.account_name or account.account_id,
        "status": "READY", "old_primary_user_id": old_primary, "primary_user_id": primary,
        "old_primary_label": names.get(old_primary, "未分配"),
        "primary_label": names.get(primary, "无负责人"), "primary_changed": primary != old_primary,
        "assignments": assignments, "warnings": list(dict.fromkeys(warnings)),
        "preview_hash": _digest({"signature": signature, "state": _state(rows), "candidates": candidates})}


def assignment_preview(db, actor, request):
    items = []
    for key in dict.fromkeys(request.account_ids):
        account = None
        try:
            account = _account(db, actor, key)
            items.append(preview_account(db, actor, request, account))
        except HTTPException as exc:
            items.append({"account_id": key, "account_name": (account.account_name or account.account_id) if account else key,
                "status": "BLOCKED", "error": exc.detail})
    return {"items": items, "ready_count": sum(x["status"] == "READY" for x in items),
        "blocked_count": sum(x["status"] == "BLOCKED" for x in items)}


def _apply(db, actor, request, account, preview):
    rows = _rows(db, account)
    by_user = {r.user_id: r for r in rows}
    now = datetime.utcnow()
    for change in preview["assignments"]:
        uid = change["user_id"]
        row = by_user.get(uid)
        if row is None:
            row = UserAccount(id=_digest([account.tenant_id, account.id, uid])[:40], tenant_id=account.tenant_id,
                account_id=account.id, user_id=uid, role="publisher", assignment_role="COLLABORATOR", assignment_status="ACTIVE")
            db.add(row)
            by_user[uid] = row
        was_active = _effective(row)
        if request.action != "EXECUTION":
            row.assignment_status = "ACTIVE"
            row.assignment_type = "MANUAL"
            row.assigned_by = actor.id
            row.expires_at = None
            if row.role not in WRITE_ACCOUNT_ROLES:
                row.role = "publisher"
        desired = change["execution_connection_id"]
        if not was_active or row.execution_connection_id != desired:
            row.execution_granted_at = now if desired else None
            row.execution_granted_by = actor.id if desired else None
        row.execution_connection_id = desired
    if request.action != "EXECUTION":
        for row in by_user.values():
            row.assignment_role = "COLLABORATOR"
        db.flush()
        by_user[preview["primary_user_id"]].assignment_role = "PRIMARY"
    db.flush()


def assignment_submit(db, actor, request):
    items = []
    for key in dict.fromkeys(request.account_ids):
        account_name = key
        try:
            account = _account(db, actor, key, lock=True)
            account_name = account.account_name or account.account_id
            audit_id = _digest([actor.id, account.tenant_id, key, request.idempotency_key])[:40]
            signature_hash = _digest(_signature(request, key))
            old = db.query(AuditLog).filter_by(id=audit_id, tenant_id=account.tenant_id, user_id=actor.id).first()
            if old:
                if old.request_data["signature_hash"] != signature_hash:
                    raise HTTPException(409, "重复请求的配置不同，请重新预览后提交")
                items.append({**old.response_data, "replayed": True})
                db.rollback()
                continue
            preview = preview_account(db, actor, request, account)
            if request.preview_hashes.get(key) != preview["preview_hash"]:
                raise HTTPException(409, "分配或授权已变化，请重新预览后保存")
            leases = AccountOperationLeaseService(db)
            from services.account_operation_lease import AccountOperationBusy
            active_lease = leases.get(account.tenant_id, key)
            if active_lease:
                raise AccountOperationBusy(active_lease)
            lease = leases.acquire(account.tenant_id, key, actor.id, "ACCOUNT_ASSIGNMENT", 120)
            _apply(db, actor, request, account, preview)
            result = {**preview, "status": "SUCCESS"}
            db.add(AuditLog(id=audit_id, tenant_id=account.tenant_id, user_id=actor.id,
                action="BULK_ASSIGN_ACCOUNT", resource_type="ad_account", resource_id=key,
                request_data={**_signature(request, key), "signature_hash": signature_hash}, response_data=result))
            leases.release(account.tenant_id, key, actor.id, lease.lease_token)
            db.commit()
            items.append(result)
        except Exception as exc:
            db.rollback()
            from services.account_operation_lease import AccountOperationBusy
            from core.logger import logger
            if isinstance(exc, HTTPException):
                message = exc.detail
            elif isinstance(exc, AccountOperationBusy):
                message = "账户已有进行中的操作，请稍后重试"
            else:
                logger.exception("Bulk assignment failed for account %s", key)
                message = "保存失败，请稍后重试"
            items.append({"account_id": key, "account_name": account_name, "status": "FAILED", "error": message})
    return {"items": items, "success_count": sum(x["status"] == "SUCCESS" for x in items),
        "failed_count": sum(x["status"] == "FAILED" for x in items)}
