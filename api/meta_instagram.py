import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin
from core.database import get_db
from core.tenant import effective_tenant_id
from models import AdAccount, AsyncTaskRecord, MetaPage, User, MetaConnectionAsset
from models.meta_instagram import MetaInstagramSnapshot
from services.account_access import can_access_account
from services.instagram_identity import snapshot_health
from services.meta.page_access import page_account_access_error
from tasks.meta_instagram_tasks import sync_instagram_task

router = APIRouter(prefix="/api/v1/meta-instagram", tags=["Meta Instagram identities"])


@router.get("")
def list_instagram_identities(
    page_id: str = Query(..., min_length=1, max_length=64),
    account_ids: list[str] | None = Query(None, max_length=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Page 和账户都显式按租户过滤，平台管理员也不能跨租户组合投放身份。
    tenant_id = effective_tenant_id(current_user)
    if not tenant_id:
        raise HTTPException(403, "请先选择租户")
    page = db.query(MetaPage).filter(MetaPage.tenant_id == tenant_id, MetaPage.page_id == page_id, MetaPage.status == "ACTIVE").first()
    if not page:
        raise HTTPException(404, "Facebook Page 不存在或无权访问")
    query = db.query(AdAccount).filter(AdAccount.tenant_id == page.tenant_id)
    requested = list(dict.fromkeys(account_ids or []))
    accounts = query.filter(AdAccount.id.in_(requested)).all() if requested else query.all()
    if requested and len(accounts) != len(requested):
        raise HTTPException(404, "部分广告账户不存在或无权访问")
    visible = []
    for account in accounts:
        allowed = can_access_account(db, current_user, account.id)
        if requested and not allowed:
            raise HTTPException(403, "无权访问所选广告账户的 Instagram 身份")
        if allowed:
            visible.append(account)
    snapshots = db.query(MetaInstagramSnapshot).filter(
        MetaInstagramSnapshot.tenant_id == page.tenant_id,
        MetaInstagramSnapshot.ad_account_id.in_([account.id for account in visible]),
    ).all() if visible else []
    by_account = {row.ad_account_id: row for row in snapshots}
    merged = {}
    health = []
    for account in visible:
        snapshot = by_account.get(account.id)
        status = snapshot_health(snapshot, account)
        if db.query(MetaConnectionAsset.id).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).first():
            from services.credential_resolver import CredentialResolver
            try:
                ref = CredentialResolver(db).for_account(account.id, actor_id=current_user.id)
                grant = db.query(MetaConnectionAsset).filter_by(connection_id=ref.connection_id, asset_type="INSTAGRAM", asset_id=account.id, status="ACTIVE").first()
            except ValueError:
                grant = None
            snapshot = grant
            status = "HEALTHY" if grant and grant.last_synced_at and grant.last_synced_at >= datetime.utcnow() - timedelta(hours=24) else "STALE"
        page_error = page_account_access_error(page, account)
        health.append({"account_pk": account.id, "account_name": account.account_name or account.account_id,
                       "sync_status": status, "page_error": page_error,
                       "last_synced_at": snapshot.last_synced_at.isoformat() if snapshot and snapshot.last_synced_at else None})
        if status != "HEALTHY" or page_error:
            continue
        for row in (snapshot.tasks if isinstance(snapshot, MetaConnectionAsset) else snapshot.items) or []:
            if page_id not in row.get("page_ids", []):
                continue
            item = merged.setdefault(row["id"], {"id": row["id"], "username": row["username"], "account_ids": []})
            item["account_ids"].append(account.id)
    return {"items": sorted(merged.values(), key=lambda row: row["username"]), "accounts": health, "source": "LOCAL_SNAPSHOT"}


@router.get("/tasks/{task_id}")
def instagram_sync_status(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    record = db.query(AsyncTaskRecord).filter(
        AsyncTaskRecord.tenant_id == effective_tenant_id(current_user),
        AsyncTaskRecord.task_type == "META_INSTAGRAM_SYNC", AsyncTaskRecord.task_id == task_id,
    ).first()
    if not record or not record.object_ids or not can_access_account(db, current_user, record.object_ids[0]):
        raise HTTPException(404, "同步任务不存在或无权访问")
    return {"task_id": task_id, "state": record.status,
            "error": "Instagram 身份同步失败，请检查授权及 Connector 状态" if record.status == "FAILURE" else None}


@router.post("/{account_pk}/sync")
def sync_instagram_identities(account_pk: str, db: Session = Depends(get_db), current_user: User = Depends(require_meta_asset_admin)):
    account = db.query(AdAccount).filter(AdAccount.tenant_id == effective_tenant_id(current_user), AdAccount.id == account_pk).first()
    if not account:
        raise HTTPException(404, "广告账户不存在或无权访问")
    if not can_access_account(db, current_user, account.id):
        raise HTTPException(403, "无权同步该广告账户的 Instagram 身份")
    active = db.query(AsyncTaskRecord).filter(
        AsyncTaskRecord.tenant_id == account.tenant_id,
        AsyncTaskRecord.task_type == "META_INSTAGRAM_SYNC", AsyncTaskRecord.status.in_(["PENDING", "STARTED", "RETRY"]),
    ).all()
    for record in active:
        if account.id in (record.object_ids or []):
            return {"status": "ALREADY_QUEUED", "task_id": record.task_id}
    task_id = uuid.uuid4().hex
    record = AsyncTaskRecord(task_id=task_id, task_type="META_INSTAGRAM_SYNC", object_type="INSTAGRAM_IDENTITY",
                             object_ids=[account.id], created_by=current_user.id)
    db.add(record)
    db.commit()
    try:
        sync_instagram_task.apply_async(args=[account.id], task_id=task_id)
    except Exception as exc:
        record.status = "FAILURE"
        record.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(503, "Instagram 同步任务派发失败，请稍后重试") from exc
    return {"status": "QUEUED", "task_id": task_id}
