import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from models import CreativeAsset, CreativeAssetGroup, User
from models.creative_asset_group import creative_asset_group_members

router = APIRouter(prefix="/api/v1/creative-asset-groups", tags=["素材分组"])


class GroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    visibility: str = "PRIVATE"


class MemberRequest(BaseModel):
    user_id: str
    can_edit: bool = False


class MoveAssetsRequest(BaseModel):
    asset_ids: list[str]
    group_id: Optional[str] = None


def _group(db: Session, group_id: str, user: User) -> CreativeAssetGroup:
    group = db.query(CreativeAssetGroup).filter(CreativeAssetGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="素材分组不存在")
    if not user.is_admin() and group.owner_id != user.id:
        member = db.execute(creative_asset_group_members.select().where(
            creative_asset_group_members.c.group_id == group_id,
            creative_asset_group_members.c.user_id == user.id,
        )).first()
        if not member:
            raise HTTPException(status_code=403, detail="无权访问该素材分组")
    return group


@router.get("")
def list_groups(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    groups = db.query(CreativeAssetGroup).order_by(CreativeAssetGroup.created_at.desc()).all()
    if user.is_admin():
        return [group.to_dict() for group in groups]
    result = []
    for group in groups:
        if group.owner_id == user.id or db.execute(creative_asset_group_members.select().where(
            creative_asset_group_members.c.group_id == group.id,
            creative_asset_group_members.c.user_id == user.id,
        )).first():
            result.append(group.to_dict())
    return result


@router.post("")
def create_group(req: GroupRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    if req.visibility not in {"PRIVATE", "TENANT"}:
        raise HTTPException(status_code=400, detail="分组可见性无效")
    group = CreativeAssetGroup(id=uuid.uuid4().hex, name=req.name.strip(), description=req.description,
                               visibility=req.visibility, owner_id=user.id)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group.to_dict()


@router.put("/{group_id}")
def update_group(group_id: str, req: GroupRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    group = _group(db, group_id, user)
    if not user.is_admin() and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有分组负责人可以修改分组")
    if req.visibility not in {"PRIVATE", "TENANT"}:
        raise HTTPException(status_code=400, detail="分组可见性无效")
    group.name, group.description, group.visibility = req.name.strip(), req.description, req.visibility
    db.commit()
    return group.to_dict()


@router.delete("/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    group = _group(db, group_id, user)
    if not user.is_admin() and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有分组负责人可以删除分组")
    db.query(CreativeAsset).filter(CreativeAsset.group_id == group_id).update({CreativeAsset.group_id: None})
    db.delete(group)
    db.commit()
    return {"success": True}


@router.put("/{group_id}/members")
def upsert_member(group_id: str, req: MemberRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    group = _group(db, group_id, user)
    if not user.is_admin() and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有分组负责人可以管理成员")
    target = db.query(User).filter(User.id == req.user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.execute(creative_asset_group_members.delete().where(
        creative_asset_group_members.c.group_id == group_id,
        creative_asset_group_members.c.user_id == req.user_id,
    ))
    db.execute(creative_asset_group_members.insert().values(group_id=group_id, user_id=req.user_id, can_edit=req.can_edit))
    db.commit()
    return {"success": True}


@router.get("/{group_id}/members")
def list_members(group_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    group = _group(db, group_id, user)
    rows = db.execute(creative_asset_group_members.select().where(
        creative_asset_group_members.c.group_id == group.id,
    )).mappings().all()
    return [dict(row) for row in rows]


@router.delete("/{group_id}/members/{user_id}")
def remove_member(group_id: str, user_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    group = _group(db, group_id, user)
    if not user.is_admin() and group.owner_id != user.id:
        raise HTTPException(status_code=403, detail="只有分组负责人可以管理成员")
    db.execute(creative_asset_group_members.delete().where(
        creative_asset_group_members.c.group_id == group_id,
        creative_asset_group_members.c.user_id == user_id,
    ))
    db.commit()
    return {"success": True}


@router.post("/move-assets")
def move_assets(req: MoveAssetsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    if not req.asset_ids:
        raise HTTPException(status_code=400, detail="至少选择一个素材")
    if req.group_id:
        group = _group(db, req.group_id, user)
        if not user.is_admin() and group.owner_id != user.id:
            member = db.execute(creative_asset_group_members.select().where(
                creative_asset_group_members.c.group_id == req.group_id,
                creative_asset_group_members.c.user_id == user.id,
                creative_asset_group_members.c.can_edit.is_(True),
            )).first()
            if not member:
                raise HTTPException(status_code=403, detail="无权向该分组移动素材")
    from api.media import _asset_query
    assets = _asset_query(db, user).filter(CreativeAsset.id.in_(req.asset_ids)).all()
    if len(assets) != len(set(req.asset_ids)):
        raise HTTPException(status_code=403, detail="包含无权操作的素材")
    for asset in assets:
        asset.group_id = req.group_id
    db.commit()
    return {"success": True, "count": len(assets)}
