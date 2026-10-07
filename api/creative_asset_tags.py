import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.audit import record_audit
from core.auth import get_current_active_user
from core.database import get_db
from core.tenant import effective_tenant_id
from models import CreativeAssetTag, CreativeAssetTagCategory, User
from models.creative_asset_tag import creative_asset_tag_links
from models.tenant import UserRole

router = APIRouter(prefix="/api/v1/creative-asset-tags", tags=["素材标签"])


class CategoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    selection_mode: Literal["SINGLE", "MULTIPLE"] = "MULTIPLE"
    sort_order: int = 0


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    selection_mode: Optional[Literal["SINGLE", "MULTIPLE"]] = None
    sort_order: Optional[int] = None
    status: Optional[Literal["ACTIVE", "INACTIVE"]] = None


class TagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    color: Optional[str] = Field(None, max_length=20)
    category_id: Optional[str] = None


class TagUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    color: Optional[str] = Field(None, max_length=20)
    status: Optional[Literal["ACTIVE", "INACTIVE"]] = None


class AssetTagsRequest(BaseModel):
    tag_ids: list[str] = Field(..., max_length=30)


class BatchAssetTagsRequest(AssetTagsRequest):
    asset_ids: list[str] = Field(..., min_length=1, max_length=100)
    mode: Literal["APPEND", "REMOVE", "REPLACE"] = "REPLACE"


def _tenant(user: User) -> str:
    tenant_id = effective_tenant_id(user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="当前用户未绑定租户")
    return tenant_id


def _assert_taxonomy_manage(user: User) -> None:
    if not (user.is_admin() or UserRole.normalize(user.role) == UserRole.MANAGER.value):
        raise HTTPException(status_code=403, detail="仅管理员或经理可维护公共标签分类")


def _category(db: Session, category_id: str, user: User) -> CreativeAssetTagCategory:
    category = db.query(CreativeAssetTagCategory).filter_by(id=category_id, tenant_id=_tenant(user)).first()
    if not category:
        raise HTTPException(status_code=404, detail="标签分类不存在或无权访问")
    return category


def validate_tag_ids(db: Session, tag_ids: list[str], tenant_id: str, *, allow_inactive=False) -> list[CreativeAssetTag]:
    ids = list(dict.fromkeys(tag_ids))
    if len(ids) > 30:
        raise HTTPException(status_code=400, detail="每个素材最多使用 30 个标签")
    tags = db.query(CreativeAssetTag).filter(
        CreativeAssetTag.tenant_id == tenant_id, CreativeAssetTag.id.in_(ids),
    ).all() if ids else []
    if len(tags) != len(ids):
        raise HTTPException(status_code=400, detail="包含不存在或无权使用的标签")
    category_ids = {tag.category_id for tag in tags}
    categories = db.query(CreativeAssetTagCategory).filter(
        CreativeAssetTagCategory.tenant_id == tenant_id,
        CreativeAssetTagCategory.id.in_(category_ids),
    ).all() if category_ids else []
    if len(categories) != len(category_ids):
        raise HTTPException(status_code=400, detail="标签分类不存在或无权使用")
    category_map = {category.id: category for category in categories}
    counts: dict[str, int] = {}
    for tag in tags:
        category = category_map[tag.category_id]
        if not allow_inactive and (tag.status != "ACTIVE" or category.status != "ACTIVE"):
            raise HTTPException(status_code=400, detail="包含已停用的标签或分类")
        counts[tag.category_id] = counts.get(tag.category_id, 0) + 1
        if category.selection_mode == "SINGLE" and counts[tag.category_id] > 1:
            raise HTTPException(status_code=400, detail=f"分类“{category.name}”只能选择一个标签")
    return tags


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    return [item.to_dict() for item in db.query(CreativeAssetTagCategory).filter_by(
        tenant_id=_tenant(user),
    ).order_by(CreativeAssetTagCategory.sort_order, CreativeAssetTagCategory.name).all()]


@router.post("/categories")
def create_category(req: CategoryRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    _assert_taxonomy_manage(user)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="分类名称不能为空")
    tenant_id = _tenant(user)
    if db.query(CreativeAssetTagCategory).filter_by(tenant_id=tenant_id, name=name).first():
        raise HTTPException(status_code=409, detail="标签分类已存在")
    category = CreativeAssetTagCategory(
        id=uuid.uuid4().hex, tenant_id=tenant_id, name=name,
        selection_mode=req.selection_mode, status="ACTIVE", sort_order=req.sort_order,
    )
    db.add(category)
    db.commit()
    return category.to_dict()


@router.patch("/categories/{category_id}")
def update_category(category_id: str, req: CategoryUpdateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    _assert_taxonomy_manage(user)
    category = _category(db, category_id, user)
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="分类名称不能为空")
        duplicate = db.query(CreativeAssetTagCategory).filter_by(tenant_id=category.tenant_id, name=name).first()
        if duplicate and duplicate.id != category.id:
            raise HTTPException(status_code=409, detail="标签分类已存在")
        category.name = name
    if req.selection_mode is not None:
        if req.selection_mode == "SINGLE" and category.selection_mode != "SINGLE":
            conflict = db.query(creative_asset_tag_links.c.asset_id).join(
                CreativeAssetTag, creative_asset_tag_links.c.tag_id == CreativeAssetTag.id,
            ).filter(CreativeAssetTag.category_id == category.id).group_by(
                creative_asset_tag_links.c.asset_id,
            ).having(func.count() > 1).first()
            if conflict:
                raise HTTPException(status_code=409, detail="已有素材在此分类中使用多个标签，请先清理")
        category.selection_mode = req.selection_mode
    if req.status is not None:
        category.status = req.status
    if req.sort_order is not None:
        category.sort_order = req.sort_order
    db.commit()
    return category.to_dict()


@router.get("")
def list_tags(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    return [tag.to_dict() for tag in db.query(CreativeAssetTag).filter_by(
        tenant_id=_tenant(user),
    ).order_by(CreativeAssetTag.name).all()]


@router.post("")
def create_tag(req: TagRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    _assert_taxonomy_manage(user)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名称不能为空")
    tenant_id = _tenant(user)
    if req.category_id:
        category = _category(db, req.category_id, user)
    else:
        # Old clients can still create tags; their default category is 未分类.
        category = db.query(CreativeAssetTagCategory).filter_by(tenant_id=tenant_id, name="未分类").first()
        if not category:
            category = CreativeAssetTagCategory(id=uuid.uuid4().hex, tenant_id=tenant_id, name="未分类")
            db.add(category)
            db.flush()
    if category.status != "ACTIVE":
        raise HTTPException(status_code=400, detail="标签分类已停用")
    if db.query(CreativeAssetTag).filter_by(tenant_id=tenant_id, category_id=category.id, name=name).first():
        raise HTTPException(status_code=409, detail="标签已存在")
    tag = CreativeAssetTag(id=uuid.uuid4().hex, tenant_id=tenant_id, category_id=category.id, name=name, color=req.color)
    db.add(tag)
    db.commit()
    return tag.to_dict()


@router.patch("/{tag_id}")
def update_tag(tag_id: str, req: TagUpdateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    _assert_taxonomy_manage(user)
    tag = db.query(CreativeAssetTag).filter_by(id=tag_id, tenant_id=_tenant(user)).first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在或无权访问")
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="标签名称不能为空")
        duplicate = db.query(CreativeAssetTag).filter_by(tenant_id=tag.tenant_id, category_id=tag.category_id, name=name).first()
        if duplicate and duplicate.id != tag.id:
            raise HTTPException(status_code=409, detail="标签已存在")
        tag.name = name
    if "color" in req.model_fields_set:
        tag.color = req.color
    if req.status is not None:
        tag.status = req.status
    db.commit()
    return tag.to_dict()


@router.put("/assets/batch")
def set_batch_asset_tags(req: BatchAssetTagsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    from api.media import _get_asset_or_404, _assert_asset_edit_access

    asset_ids = list(dict.fromkeys(req.asset_ids))
    requested = list(dict.fromkeys(req.tag_ids))
    incoming = validate_tag_ids(db, requested, _tenant(user), allow_inactive=req.mode == "REMOVE")
    assets = [_get_asset_or_404(db, asset_id, user) for asset_id in asset_ids]
    for asset in assets:
        _assert_asset_edit_access(db, asset, user)
    result = {}
    assignments = {}
    for asset in assets:
        current = {tag.id: tag for tag in asset.tags}
        if req.mode == "REPLACE":
            final = {tag.id: tag for tag in incoming}
        elif req.mode == "APPEND":
            final = {**current, **{tag.id: tag for tag in incoming}}
        else:
            final = {tag_id: tag for tag_id, tag in current.items() if tag_id not in requested}
        validate_tag_ids(db, list(final), _tenant(user), allow_inactive=True)
        assignments[asset.id] = list(final.values())
        result[asset.id] = list(final)
    for asset in assets:
        asset.tags = assignments[asset.id]
    db.commit()
    record_audit(db, action="BATCH_UPDATE_CREATIVE_ASSET_TAGS", resource_type="creative_asset", resource_id=asset_ids[0], user_id=user.id,
                 request_data={"asset_ids": asset_ids, "tag_ids": requested, "mode": req.mode}, response_data={"count": len(asset_ids)})
    return {"asset_ids": asset_ids, "tag_ids_by_asset": result}


@router.put("/assets/{asset_id}")
def set_asset_tags(asset_id: str, req: AssetTagsRequest, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    from api.media import _get_asset_or_404, _assert_asset_edit_access

    asset = _get_asset_or_404(db, asset_id, user)
    _assert_asset_edit_access(db, asset, user)
    tags = validate_tag_ids(db, req.tag_ids, _tenant(user), allow_inactive=True)
    existing_ids = {tag.id for tag in asset.tags}
    if any((tag.status != "ACTIVE" or tag.category.status != "ACTIVE") and tag.id not in existing_ids for tag in tags):
        raise HTTPException(status_code=400, detail="不能新增加已停用的标签或分类")
    asset.tags = tags
    db.commit()
    record_audit(db, action="UPDATE_CREATIVE_ASSET_TAGS", resource_type="creative_asset", resource_id=asset.id, user_id=user.id,
                 request_data={"tag_ids": list(req.tag_ids)}, response_data={"tag_ids": [tag.id for tag in tags]})
    return {"asset_id": asset.id, "tag_ids": [tag.id for tag in tags]}
