"""Meta Custom Audience 资产与强制排除配置。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin
from core.audit import record_audit
from core.database import get_db
from models import AdAccount, AsyncTaskRecord, MetaAudienceAsset, User
from services.account_access import can_access_account
from tasks.meta_audience_tasks import sync_custom_audiences_task


router = APIRouter(prefix="/api/v1/meta-audiences", tags=["Meta 自定义受众"])


def _account(db: Session, account_pk: str) -> AdAccount:
    row = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not row:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    return row


@router.get("")
def list_audiences(
    account_pk: str = Query(..., description="系统广告账户主键"),
    q: Optional[str] = Query(None),
    required_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    _account(db, account_pk)
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权访问该广告账户的受众资产")
    query = db.query(MetaAudienceAsset).filter(MetaAudienceAsset.ad_account_id == account_pk)
    if required_only:
        query = query.filter(MetaAudienceAsset.is_required_exclusion.is_(True))
    if q:
        query = query.filter(MetaAudienceAsset.name.ilike(f"%{q.strip()}%"))
    return [item.to_dict() for item in query.order_by(MetaAudienceAsset.name).all()]


@router.post("/{account_pk}/sync")
def sync_audiences(
    account_pk: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_meta_asset_admin),
):
    account = _account(db, account_pk)
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权管理该广告账户的受众资产")
    active = db.query(AsyncTaskRecord).filter(
        AsyncTaskRecord.task_type == "META_CUSTOM_AUDIENCE_SYNC",
        AsyncTaskRecord.object_type == "CUSTOM_AUDIENCE",
        AsyncTaskRecord.status.in_(["PENDING", "STARTED", "RETRY"]),
    ).order_by(AsyncTaskRecord.created_at.desc()).all()
    for row in active:
        if account_pk in [str(value) for value in (row.object_ids or [])]:
            return {
                "status": "ALREADY_QUEUED",
                "task_id": row.task_id,
                "account_pk": account_pk,
                "account_id": account.account_id,
            }
    task = sync_custom_audiences_task.delay(account_pk)
    db.add(AsyncTaskRecord(
        task_id=task.id,
        task_type="META_CUSTOM_AUDIENCE_SYNC",
        object_type="CUSTOM_AUDIENCE",
        object_ids=[account_pk],
        created_by=current_user.id,
    ))
    db.commit()
    result = {"status": "QUEUED", "task_id": task.id, "account_pk": account_pk, "account_id": account.account_id}
    record_audit(
        db,
        action="SYNC_META_CUSTOM_AUDIENCES",
        resource_type="meta_audience_asset",
        resource_id=account_pk,
        user_id=current_user.id,
        request_data={"account_pk": account_pk, "meta_account_id": account.account_id},
        response_data={"status": result["status"], "task_id": task.id},
        request=request,
    )
    return result


class RequiredExclusionRequest(BaseModel):
    audience_ids: list[str] = Field(default_factory=list, description="Meta Audience ID 列表")


@router.put("/{account_pk}/required-exclusions")
def set_required_exclusions(
    account_pk: str,
    req: RequiredExclusionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_meta_asset_admin),
):
    account = _account(db, account_pk)
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权管理该广告账户的受众资产")
    ids = {str(value).strip() for value in req.audience_ids if str(value).strip()}
    rows = db.query(MetaAudienceAsset).filter(MetaAudienceAsset.ad_account_id == account.id).all()
    known = {row.meta_audience_id for row in rows}
    unknown = sorted(ids - known)
    if unknown:
        raise HTTPException(status_code=400, detail={"code": "AUDIENCE_NOT_SYNCED", "audience_ids": unknown})
    for row in rows:
        row.is_required_exclusion = row.meta_audience_id in ids
    db.commit()
    required = [row.to_dict() for row in rows if row.is_required_exclusion]
    result = {"account_id": account.account_id, "required_exclusions": required}
    record_audit(
        db,
        action="UPDATE_REQUIRED_META_AUDIENCE_EXCLUSIONS",
        resource_type="meta_audience_asset",
        resource_id=account_pk,
        user_id=current_user.id,
        request_data={"account_pk": account_pk, "audience_ids": sorted(ids)},
        response_data={"account_id": account.account_id, "required_audience_ids": [item["meta_audience_id"] for item in required]},
        request=request,
    )
    return result
