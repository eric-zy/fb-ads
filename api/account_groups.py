import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from core.auth import require_admin
from core.database import get_db
from models import AccountGroup, AdAccount, User
from core.audit import record_audit

router = APIRouter(prefix="/api/v1/account-groups", tags=["账户组"])
class GroupPayload(BaseModel):
    name: str
    description: Optional[str] = None
    account_ids: list[str] = []
    user_ids: list[str] = []

def _get(db, group_id):
    group = db.query(AccountGroup).filter(AccountGroup.id == group_id).first()
    if not group: raise HTTPException(status_code=404, detail="账户组不存在")
    return group

@router.get("")
def list_groups(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [g.to_dict() for g in db.query(AccountGroup).order_by(AccountGroup.created_at.desc()).all()]

@router.post("", status_code=201)
def create_group(payload: GroupPayload, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if db.query(AccountGroup).filter(AccountGroup.name == payload.name).first(): raise HTTPException(status_code=400, detail="账户组名称已存在")
    group = AccountGroup(id=str(uuid.uuid4()), name=payload.name, description=payload.description)
    group.accounts = db.query(AdAccount).filter(AdAccount.id.in_(payload.account_ids)).all() if payload.account_ids else []
    group.users = db.query(User).filter(User.id.in_(payload.user_ids)).all() if payload.user_ids else []
    db.add(group); db.commit(); db.refresh(group)
    record_audit(db, action="CREATE_ACCOUNT_GROUP", resource_type="account_group", resource_id=group.id, user_id=current_user.id, request_data=payload.model_dump(), request=request)
    return group.to_dict()

@router.put("/{group_id}")
def update_group(group_id: str, payload: GroupPayload, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    group = _get(db, group_id); group.name = payload.name; group.description = payload.description
    group.accounts = db.query(AdAccount).filter(AdAccount.id.in_(payload.account_ids)).all() if payload.account_ids else []
    group.users = db.query(User).filter(User.id.in_(payload.user_ids)).all() if payload.user_ids else []
    db.commit(); db.refresh(group)
    record_audit(db, action="UPDATE_ACCOUNT_GROUP", resource_type="account_group", resource_id=group.id, user_id=current_user.id, request_data=payload.model_dump(), request=request)
    return group.to_dict()

@router.delete("/{group_id}")
def delete_group(group_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    group = _get(db, group_id); db.delete(group); db.commit()
    record_audit(db, action="DELETE_ACCOUNT_GROUP", resource_type="account_group", resource_id=group_id, user_id=current_user.id, request_data={}, request=request)
    return {"success": True}
