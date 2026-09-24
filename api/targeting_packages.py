"""地区组和定向包管理接口。"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from models import AdAccount, RegionGroup, TargetingPackage, User
from services.account_access import can_access_account
from services.targeting_catalog import normalize_targeting, targeting_preflight_errors, placement_preflight_errors


region_router = APIRouter(prefix="/api/v1/region-groups", tags=["地区组"])
package_router = APIRouter(prefix="/api/v1/targeting-packages", tags=["定向包"])


class RegionGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    geo_locations: Dict[str, Any] = Field(default_factory=dict)
    excluded_geo_locations: Dict[str, Any] = Field(default_factory=dict)
    account_ids: List[str] = Field(default_factory=list)
    description: Optional[str] = Field(default=None, max_length=2000)


class TargetingPackageRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    targeting_json: Dict[str, Any] = Field(default_factory=dict)
    placement_json: Dict[str, Any] = Field(default_factory=dict)
    account_ids: List[str] = Field(default_factory=list)
    region_group_ids: List[str] = Field(default_factory=list)
    description: Optional[str] = Field(default=None, max_length=2000)


def _unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _validate_accounts(db: Session, user: User, account_ids: List[str]) -> List[str]:
    ids = _unique(account_ids)
    for account_id in ids:
        account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=400, detail=f"广告账户不存在：{account_id}")
        if not can_access_account(db, user, account_id):
            raise HTTPException(status_code=403, detail=f"无权绑定广告账户：{account_id}")
    return ids


def _validate_region_ids(db: Session, region_group_ids: List[str]) -> List[str]:
    ids = _unique(region_group_ids)
    if not ids:
        return []
    found = {row.id for row in db.query(RegionGroup).filter(RegionGroup.id.in_(ids)).all()}
    missing = sorted(set(ids) - found)
    if missing:
        raise HTTPException(status_code=400, detail=f"地区组不存在：{', '.join(missing)}")
    return ids


def _validate_region_payload(req: RegionGroupRequest) -> tuple[dict, dict]:
    geo = dict(req.geo_locations or {})
    excluded = dict(req.excluded_geo_locations or {})
    if not any(geo.get(key) for key in ("countries", "regions", "cities", "zips", "custom_locations")):
        raise HTTPException(status_code=400, detail="地区组至少需要一个国家、地区、城市或邮编")
    try:
        normalized = normalize_targeting({
            "geo_locations": geo,
            "excluded_geo_locations": excluded,
        })
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    geo = normalized.get("geo_locations") or {}
    excluded = normalized.get("excluded_geo_locations") or {}
    errors = targeting_preflight_errors("地区组", normalized)
    if errors:
        raise HTTPException(status_code=400, detail=errors[0]["message"])
    return geo, excluded


@region_router.get("")
def list_region_groups(
    status: Optional[str] = Query("ACTIVE"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    query = db.query(RegionGroup)
    if status:
        query = query.filter(RegionGroup.status == status.upper())
    return [item.to_dict() for item in query.order_by(RegionGroup.updated_at.desc()).all()]


@region_router.post("", status_code=201)
def create_region_group(
    req: RegionGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    geo, excluded = _validate_region_payload(req)
    account_ids = _validate_accounts(db, current_user, req.account_ids)
    item = RegionGroup(
        id=uuid.uuid4().hex,
        name=req.name.strip(),
        geo_locations=geo,
        excluded_geo_locations=excluded,
        account_ids=account_ids,
        description=req.description,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@region_router.put("/{group_id}")
def update_region_group(
    group_id: str,
    req: RegionGroupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    item = db.query(RegionGroup).filter(RegionGroup.id == group_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="地区组不存在")
    geo, excluded = _validate_region_payload(req)
    item.name = req.name.strip()
    item.geo_locations = geo
    item.excluded_geo_locations = excluded
    item.account_ids = _validate_accounts(db, current_user, req.account_ids)
    item.description = req.description
    db.commit()
    db.refresh(item)
    return item.to_dict()


@region_router.delete("/{group_id}")
def delete_region_group(
    group_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    item = db.query(RegionGroup).filter(RegionGroup.id == group_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="地区组不存在")
    item.status = "ARCHIVED"
    db.commit()
    return {"id": group_id, "status": item.status}


def _validate_package_payload(req: TargetingPackageRequest) -> dict:
    try:
        targeting = normalize_targeting(req.targeting_json)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    errors = targeting_preflight_errors("定向包", targeting)
    if errors:
        raise HTTPException(status_code=400, detail=errors[0]["message"])
    placement_errors = placement_preflight_errors("定向包版位", req.placement_json)
    if placement_errors:
        raise HTTPException(status_code=400, detail=placement_errors[0]["message"])
    return targeting


@package_router.get("")
def list_targeting_packages(
    status: Optional[str] = Query("ACTIVE"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    query = db.query(TargetingPackage)
    if status:
        query = query.filter(TargetingPackage.status == status.upper())
    return [item.to_dict() for item in query.order_by(TargetingPackage.updated_at.desc()).all()]


@package_router.post("", status_code=201)
def create_targeting_package(
    req: TargetingPackageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    targeting = _validate_package_payload(req)
    account_ids = _validate_accounts(db, current_user, req.account_ids)
    region_ids = _validate_region_ids(db, req.region_group_ids)
    item = TargetingPackage(
        id=uuid.uuid4().hex,
        name=req.name.strip(),
        targeting_json=targeting,
        placement_json=dict(req.placement_json or {}),
        account_ids=account_ids,
        region_group_ids=region_ids,
        description=req.description,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item.to_dict()


@package_router.put("/{package_id}")
def update_targeting_package(
    package_id: str,
    req: TargetingPackageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    item = db.query(TargetingPackage).filter(TargetingPackage.id == package_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="定向包不存在")
    targeting = _validate_package_payload(req)
    item.name = req.name.strip()
    item.targeting_json = targeting
    item.placement_json = dict(req.placement_json or {})
    item.account_ids = _validate_accounts(db, current_user, req.account_ids)
    item.region_group_ids = _validate_region_ids(db, req.region_group_ids)
    item.description = req.description
    db.commit()
    db.refresh(item)
    return item.to_dict()


@package_router.delete("/{package_id}")
def delete_targeting_package(
    package_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_active_user),
):
    item = db.query(TargetingPackage).filter(TargetingPackage.id == package_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="定向包不存在")
    item.status = "ARCHIVED"
    db.commit()
    return {"id": package_id, "status": item.status}
