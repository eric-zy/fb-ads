from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.auth import require_admin
from core.database import get_db
from core.tenant import effective_tenant_id
from models import User, AdAccount, BusinessAssetAccess, UserAccount, AccountAssignmentRule
from services.account_dispatch import AccountDispatchService

router = APIRouter(prefix="/api/v1/account-dispatch", tags=["广告账户调度"])

class RuleRequest(BaseModel):
    name: str
    target_user_id: str
    priority: int = 100
    rule_type: str = "FIXED_USER"
    rule_config: dict = {}

@router.post("/rules")
def create_rule(payload: RuleRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    tenant_id = effective_tenant_id(current_user)
    rule = __import__("models").AccountAssignmentRule(id=__import__("uuid").uuid4().hex, tenant_id=tenant_id, name=payload.name, target_user_id=payload.target_user_id, priority=str(payload.priority), rule_type=payload.rule_type, rule_config=payload.rule_config)
    db.add(rule); db.commit()
    return {"id": rule.id, "status": rule.status}

@router.get("/rules")
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    tenant_id = effective_tenant_id(current_user)
    rows = db.query(AccountAssignmentRule).filter(AccountAssignmentRule.tenant_id == tenant_id).order_by(AccountAssignmentRule.priority.asc()).all()
    return {"items": [{"id": r.id, "name": r.name, "priority": int(r.priority), "rule_type": r.rule_type, "rule_config": r.rule_config or {}, "target_user_id": r.target_user_id, "status": r.status} for r in rows], "total": len(rows)}

@router.patch("/rules/{rule_id}/status")
def update_rule_status(rule_id: str, status: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if status not in {"ACTIVE", "DISABLED"}:
        raise HTTPException(status_code=400, detail="status 必须为 ACTIVE 或 DISABLED")
    rule = db.query(AccountAssignmentRule).filter(AccountAssignmentRule.id == rule_id, AccountAssignmentRule.tenant_id == effective_tenant_id(current_user)).first()
    if not rule:
        raise HTTPException(status_code=404, detail="分配规则不存在")
    rule.status = status
    db.commit()
    return {"id": rule.id, "status": rule.status}

@router.get("/accounts/{account_id}/assignments")
def list_assignments(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rows = db.query(UserAccount).filter(UserAccount.tenant_id == effective_tenant_id(current_user), UserAccount.account_id == account_id).order_by(UserAccount.assigned_at.desc()).all()
    return {"items": [{"id": r.id, "user_id": r.user_id, "status": r.assignment_status, "type": r.assignment_type, "assigned_at": r.assigned_at.isoformat() if r.assigned_at else None, "expires_at": r.expires_at.isoformat() if r.expires_at else None} for r in rows], "total": len(rows)}

@router.post("/accounts/{account_id}/dispatch")
def dispatch(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    try:
        row = AccountDispatchService(db).dispatch(effective_tenant_id(current_user), account_id, current_user.id)
        return {"status": "ASSIGNED", "user_id": row.user_id, "account_id": account_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.post("/accounts/{account_id}/release")
def release(account_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    count = AccountDispatchService(db).release(effective_tenant_id(current_user), account_id, current_user.id)
    return {"status": "RELEASED", "account_id": account_id, "released": count}

@router.post("/dispatch-unassigned")
def dispatch_unassigned(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """将当前账户池内尚未分配的账户按规则批量分配。"""
    tenant_id = effective_tenant_id(current_user)
    accounts = db.query(AdAccount.id).join(
        BusinessAssetAccess, BusinessAssetAccess.asset_id == AdAccount.id
    ).filter(
        AdAccount.tenant_id == tenant_id,
        AdAccount.system_status == "ACTIVE",
        BusinessAssetAccess.tenant_id == tenant_id,
        BusinessAssetAccess.status == "ACTIVE",
    ).all()
    assigned = 0
    skipped = 0
    errors = []
    service = AccountDispatchService(db)
    for (account_id,) in accounts:
        exists = db.query(UserAccount.id).filter(
            UserAccount.tenant_id == tenant_id,
            UserAccount.account_id == account_id,
            UserAccount.assignment_status == "ACTIVE",
        ).first()
        if exists:
            skipped += 1
            continue
        try:
            service.dispatch(tenant_id, account_id, current_user.id)
            assigned += 1
        except ValueError as exc:
            errors.append({"account_id": account_id, "reason": str(exc)})
    return {"status": "COMPLETED", "assigned": assigned, "skipped": skipped, "errors": errors}
