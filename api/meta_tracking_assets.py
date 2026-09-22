from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin
from core.database import get_db
from models import AdAccount, AsyncTaskRecord, MetaTrackingAsset, User
from services.account_access import can_access_account
from services.meta_tracking_asset_service import MetaTrackingAssetSyncService
from tasks.meta_tracking_asset_tasks import sync_tracking_assets_task

router = APIRouter(prefix="/api/v1/meta-tracking-assets", tags=["Meta Pixel/Dataset"])


@router.get("")
def list_tracking_assets(
    account_ids: list[str] = Query(..., min_length=1, max_length=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """按目标广告账户读取当前授权可用的 Pixel / Dataset。

    返回资产关联的系统账户主键，前端据此只展示所有已选账户的交集，
    防止多账户批量投放时误把 A 账户的 Pixel 带到 B 账户。
    """
    requested = list(dict.fromkeys(str(value).strip() for value in account_ids if str(value).strip()))
    if not requested:
        return {"items": [], "account_count": 0, "synced_at": datetime.utcnow().isoformat()}

    accounts = db.query(AdAccount).filter(AdAccount.id.in_(requested)).all()
    by_id = {account.id: account for account in accounts}
    missing = [account_id for account_id in requested if account_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail="部分广告账户不存在或已不可用")
    for account in accounts:
        if not can_access_account(db, current_user, account.id):
            raise HTTPException(status_code=403, detail="无权访问所选广告账户的 Pixel/数据集")

    merged: dict[tuple[str, str], dict] = {}
    sync_service = MetaTrackingAssetSyncService(db)
    for account in accounts:
        try:
            result = sync_service.sync_account(account.id)
            rows = result.get("items", [])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        for raw in rows if isinstance(rows, list) else []:
            asset_id = str(raw.get("meta_asset_id") or raw.get("id") or "").strip()
            asset_type = str(raw.get("asset_type") or "PIXEL").upper()
            if not asset_id or asset_type not in {"PIXEL", "DATASET"}:
                continue
            if raw.get("usable") is False or raw.get("status") != "ACTIVE":
                continue
            key = (asset_type, asset_id)
            item = merged.setdefault(key, {
                "id": asset_id,
                "name": str(raw.get("name") or asset_id),
                "asset_type": asset_type,
                "account_ids": [],
                "account_names": [],
                "last_fired_time": raw.get("last_fired_time"),
                "status": raw.get("status") or "ACTIVE",
                "usable": raw.get("usable", True),
                "last_synced_at": raw.get("last_synced_at"),
                "last_sync_error": raw.get("last_sync_error"),
            })
            if account.id not in item["account_ids"]:
                item["account_ids"].append(account.id)
                item["account_names"].append(account.account_name or account.account_id)

    return {
        "items": sorted(merged.values(), key=lambda item: (item["asset_type"], item["name"].lower())),
        "account_count": len(accounts),
        "synced_at": datetime.utcnow().isoformat(),
    }


@router.get("/health")
def tracking_asset_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """返回所有可见广告账户的 Pixel / Dataset 健康概览，不触发 Meta 请求。"""
    accounts = db.query(AdAccount).order_by(AdAccount.account_name, AdAccount.account_id).all()
    visible = [account for account in accounts if can_access_account(db, current_user, account.id)]
    account_ids = [account.id for account in visible]
    assets = db.query(MetaTrackingAsset).filter(
        MetaTrackingAsset.ad_account_id.in_(account_ids)
    ).all() if account_ids else []
    by_account: dict[str, list[MetaTrackingAsset]] = {}
    for asset in assets:
        by_account.setdefault(asset.ad_account_id, []).append(asset)

    now = datetime.utcnow()
    items = []
    for account in visible:
        rows = by_account.get(account.id, [])
        latest = max((row.last_synced_at for row in rows if row.last_synced_at), default=None)
        age_hours = (now - latest).total_seconds() / 3600 if latest else None
        if not latest:
            sync_status = "NEVER"
        elif age_hours is not None and age_hours > 24:
            sync_status = "STALE"
        elif any(row.last_sync_error for row in rows):
            sync_status = "ERROR"
        else:
            sync_status = "HEALTHY"
        items.append({
            "account_pk": account.id,
            "account_id": account.account_id,
            "account_name": account.account_name or account.account_id,
            "owner_type": account.owner_type,
            "business_name": account.business.name if account.business else None,
            "sync_status": sync_status,
            "last_synced_at": latest.isoformat() if latest else None,
            "asset_count": len(rows),
            "usable_count": sum(1 for row in rows if row.usable and row.status == "ACTIVE"),
            "assets": [row.to_dict() for row in sorted(rows, key=lambda row: (row.asset_type, row.name))],
        })
    return {
        "items": items,
        "summary": {
            "account_count": len(items),
            "healthy_count": sum(1 for item in items if item["sync_status"] == "HEALTHY"),
            "stale_count": sum(1 for item in items if item["sync_status"] in {"STALE", "NEVER"}),
            "error_count": sum(1 for item in items if item["sync_status"] == "ERROR"),
        },
    }


@router.post("/{account_pk}/sync")
def sync_tracking_assets(
    account_pk: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_meta_asset_admin),
):
    """手动刷新单个广告账户的 Pixel / Dataset，并保留同步状态。"""
    account = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not account:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权管理该广告账户的 Pixel/数据集")
    active = db.query(AsyncTaskRecord).filter(
        AsyncTaskRecord.task_type == "META_TRACKING_ASSET_SYNC",
        AsyncTaskRecord.object_type == "TRACKING_ASSET",
        AsyncTaskRecord.status.in_(["PENDING", "STARTED", "RETRY"]),
    ).order_by(AsyncTaskRecord.created_at.desc()).all()
    for row in active:
        if account_pk in [str(value) for value in (row.object_ids or [])]:
            return {"status": "ALREADY_QUEUED", "task_id": row.task_id, "account_pk": account_pk}
    task = sync_tracking_assets_task.delay(account_pk)
    db.add(AsyncTaskRecord(
        task_id=task.id,
        task_type="META_TRACKING_ASSET_SYNC",
        object_type="TRACKING_ASSET",
        object_ids=[account_pk],
        created_by=current_user.id,
    ))
    db.commit()
    return {
        "status": "QUEUED",
        "task_id": task.id,
        "account_pk": account_pk,
        "account_id": account.account_id,
    }
