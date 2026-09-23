"""Meta Custom Audience 资产与强制排除配置。"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin
from core.audit import record_audit
from core.database import get_db
from models import AdAccount, AsyncTaskRecord, MetaAudienceAsset, MetaAudienceExclusionPolicy, User
from services.account_access import can_access_account
from services.meta_audience_policy import resolve_required_exclusions, sync_policy_rows
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
        required_ids = {
            item.meta_audience_id
            for item in resolve_required_exclusions(db, account_pk)["assets"]
        }
        query = query.filter(MetaAudienceAsset.meta_audience_id.in_(required_ids or ["__none__"]))
    if q:
        query = query.filter(MetaAudienceAsset.name.ilike(f"%{q.strip()}%"))
    items = query.order_by(MetaAudienceAsset.name).all()
    policy_by_asset = {
        row.meta_audience_asset_id: row
        for row in db.query(MetaAudienceExclusionPolicy).filter(
            MetaAudienceExclusionPolicy.ad_account_id == account_pk,
            MetaAudienceExclusionPolicy.status == "ACTIVE",
        ).all()
    }
    result = []
    for item in items:
        payload = item.to_dict()
        policy = policy_by_asset.get(item.id)
        if policy:
            payload.update({
                "policy_reason_code": policy.reason_code,
                "policy_reason_note": policy.reason_note,
                "policy_version": policy.policy_version,
                "policy_effective_from": policy.effective_from.isoformat() if policy.effective_from else None,
                "policy_effective_until": policy.effective_until.isoformat() if policy.effective_until else None,
            })
        result.append(payload)
    return result


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
    reason_code: str = Field(default="LEGACY_MIGRATION", max_length=32)
    reason_note: Optional[str] = Field(default=None, max_length=2000)
    effective_from: Optional[str] = Field(default=None, description="ISO 8601 UTC 时间")
    effective_until: Optional[str] = Field(default=None, description="ISO 8601 UTC 时间")


def _parse_policy_datetime(value: Optional[str], field_name: str):
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} 必须是 ISO 8601 时间") from exc


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
    try:
        policies = sync_policy_rows(
            db,
            account.id,
            ids,
            created_by=current_user.id,
            approved_by=current_user.id,
            reason_code=req.reason_code.strip().upper() or "LEGACY_MIGRATION",
            reason_note=req.reason_note,
            effective_from=_parse_policy_datetime(req.effective_from, "effective_from"),
            effective_until=_parse_policy_datetime(req.effective_until, "effective_until"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    resolved = resolve_required_exclusions(db, account.id)
    required = [row.to_dict() for row in resolved["assets"]]
    result = {
        "account_id": account.account_id,
        "required_exclusions": required,
        "policies": [row.to_dict() for row in policies],
        "policy_snapshot": resolved["snapshot"],
    }
    record_audit(
        db,
        action="UPDATE_REQUIRED_META_AUDIENCE_EXCLUSIONS",
        resource_type="meta_audience_asset",
        resource_id=account_pk,
        user_id=current_user.id,
        request_data={"account_pk": account_pk, "audience_ids": sorted(ids)},
        response_data={
            "account_id": account.account_id,
            "required_audience_ids": [item["meta_audience_id"] for item in required],
            "policy_snapshot": resolved["snapshot"],
        },
        request=request,
    )
    return result


@router.get("/{account_pk}/policy-status")
def policy_status(
    account_pk: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """返回账户强制排除策略的可投放状态，供后台和工作台展示。"""
    _account(db, account_pk)
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权访问该广告账户的策略状态")
    resolved = resolve_required_exclusions(db, account_pk)
    blocked = []
    stale = []
    now = datetime.utcnow()
    for asset in resolved["assets"]:
        delivery_status = str(asset.delivery_status or "").upper()
        if asset.sync_status in {"MISSING", "DELETED", "EXPIRED", "UNAVAILABLE"} or any(
            marker in delivery_status for marker in ("DELETED", "EXPIRED", "UNAVAILABLE")
        ):
            blocked.append({"audience_id": asset.meta_audience_id, "reason": "UNAVAILABLE"})
        elif not asset.last_synced_at or asset.last_synced_at < now - timedelta(days=7):
            stale.append({"audience_id": asset.meta_audience_id, "reason": "STALE"})
    return {
        "account_id": account_pk,
        "required_count": len(resolved["assets"]),
        "blocked": blocked,
        "stale": stale,
        "can_publish": not blocked and not stale,
        "policy_snapshot": resolved["snapshot"],
    }
