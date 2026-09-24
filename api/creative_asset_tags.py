import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from models import CreativeAsset, CreativeAssetTag, User
from models.creative_asset_tag import creative_asset_tag_links
from core.audit import record_audit

router = APIRouter(prefix="/api/v1/creative-asset-tags", tags=["素材标签"])


class TagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = None


class AssetTagsRequest(BaseModel):
    tag_ids: list[str]


class BatchAssetTagsRequest(BaseModel):
    asset_ids: list[str] = Field(..., min_length=1)
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


@router.put("/assets/batch")
def set_batch_asset_tags(req: BatchAssetTagsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    from api.media import _get_asset_or_404, _assert_asset_edit_access
    asset_ids = list(dict.fromkeys(req.asset_ids))
    tag_ids = list(dict.fromkeys(req.tag_ids))
    tags = db.query(CreativeAssetTag).filter(CreativeAssetTag.id.in_(tag_ids)).all() if tag_ids else []
    if len(tags) != len(tag_ids):
        raise HTTPException(status_code=400, detail="包含不存在或无权使用的标签")
    assets = [_get_asset_or_404(db, asset_id, user) for asset_id in asset_ids]
    for asset in assets:
        _assert_asset_edit_access(db, asset, user)
        asset.tags = tags
    db.commit()
    record_audit(db, action="BATCH_UPDATE_CREATIVE_ASSET_TAGS", resource_type="creative_asset", resource_id=asset_ids[0], user_id=user.id, request_data={"asset_ids": asset_ids, "tag_ids": tag_ids}, response_data={"count": len(asset_ids)})
    return {"asset_ids": asset_ids, "tag_ids": [tag.id for tag in tags]}


@router.put("/assets/{asset_id}")
def set_asset_tags(asset_id: str, req: AssetTagsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    from api.media import _get_asset_or_404
    asset = _get_asset_or_404(db, asset_id, user)
    from api.media import _assert_asset_edit_access
    _assert_asset_edit_access(db, asset, user)
    tags = db.query(CreativeAssetTag).filter(CreativeAssetTag.id.in_(set(req.tag_ids))).all() if req.tag_ids else []
    if len(tags) != len(set(req.tag_ids)):
        raise HTTPException(status_code=400, detail="包含不存在或无权使用的标签")
    asset.tags = tags
    db.commit()
    record_audit(db, action="UPDATE_CREATIVE_ASSET_TAGS", resource_type="creative_asset", resource_id=asset.id, user_id=user.id, request_data={"tag_ids": list(req.tag_ids)}, response_data={"tag_ids": [tag.id for tag in tags]})
    return {"asset_id": asset.id, "tag_ids": [tag.id for tag in tags]}
