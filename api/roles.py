"""角色与权限模板管理。"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from core.auth import require_admin
from core.database import get_db
from models import Role, User
from core.audit import record_audit

router = APIRouter(prefix="/api/v1/roles", tags=["角色权限"])

class RolePayload(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    permissions: List[str] = []

@router.get("")
def list_roles(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [r.to_dict() for r in db.query(Role).order_by(Role.created_at.asc()).all()]

@router.post("", status_code=201)
def create_role(payload: RolePayload, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    if db.query(Role).filter(Role.code == payload.code.strip()).first():
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role = Role(id=str(uuid.uuid4()), code=payload.code.strip(), name=payload.name,
                description=payload.description, permissions=sorted(set(payload.permissions)))
    db.add(role); db.commit(); db.refresh(role)
    record_audit(db, action="CREATE_ROLE", resource_type="role", resource_id=role.id, user_id=current_user.id, request_data=payload.model_dump(), request=request)
    return role.to_dict()

@router.put("/{role_id}")
def update_role(role_id: str, payload: RolePayload, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role: raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_system and payload.code != role.code: raise HTTPException(status_code=400, detail="系统角色不可修改编码")
    role.code, role.name, role.description = payload.code.strip(), payload.name, payload.description
    role.permissions = sorted(set(payload.permissions)); db.commit(); db.refresh(role)
    record_audit(db, action="UPDATE_ROLE", resource_type="role", resource_id=role.id, user_id=current_user.id, request_data=payload.model_dump(), request=request)
    return role.to_dict()

@router.delete("/{role_id}")
def delete_role(role_id: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role: raise HTTPException(status_code=404, detail="角色不存在")
    if role.is_system: raise HTTPException(status_code=400, detail="系统角色不可删除")
    db.delete(role); db.commit()
    record_audit(db, action="DELETE_ROLE", resource_type="role", resource_id=role_id, user_id=current_user.id, request_data={}, request=request)
    return {"success": True}
