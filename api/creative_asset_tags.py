import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from models import CreativeAsset, CreativeAssetTag, User
from models.creative_asset_tag import creative_asset_tag_links

router = APIRouter(prefix="/api/v1/creative-asset-tags", tags=["素材标签"])


class TagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = None


class AssetTagsRequest(BaseModel):
    tag_ids: list[str]


@router.get("")
def list_tags(db: Session = Depends(get_db), _: User = Depends(get_current_active_user)):
    return [tag.to_dict() for tag in db.query(CreativeAssetTag).order_by(CreativeAssetTag.name).all()]


@router.post("")
def create_tag(req: TagRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    name = req.name.strip()
    if db.query(CreativeAssetTag).filter(CreativeAssetTag.name == name).first():
        raise HTTPException(status_code=409, detail="标签已存在")
    tag = CreativeAssetTag(id=uuid.uuid4().hex, name=name, color=req.color)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag.to_dict()


@router.put("/assets/{asset_id}")
def set_asset_tags(asset_id: str, req: AssetTagsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    from api.media import _get_asset_or_404
    asset = _get_asset_or_404(db, asset_id, user)
    tags = db.query(CreativeAssetTag).filter(CreativeAssetTag.id.in_(set(req.tag_ids))).all() if req.tag_ids else []
    if len(tags) != len(set(req.tag_ids)):
        raise HTTPException(status_code=400, detail="包含不存在或无权使用的标签")
    asset.tags = tags
    db.commit()
    return {"asset_id": asset.id, "tag_ids": [tag.id for tag in tags]}
