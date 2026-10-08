"""Facebook Page 管理接口。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, require_meta_asset_admin as require_admin
from core.database import get_db
from core.enums import CredentialStatus
from core.tenant import bypass_tenant, effective_tenant_id, tenant_scope
from models import AdAccount, Credential, MetaAccount, MetaPage, User, MetaConnection, MetaConnectionAsset
from tasks.meta_sync_tasks import sync_meta_pages_task
from config.settings import settings
from services.fb_connector_client import FBConnectorError
from services.meta.connector_page_sync import sync_connector_pages
from services.meta_connection_service import connection_health

router = APIRouter(prefix="/api/v1/meta-pages", tags=["Facebook Pages"])


def _query_for_user(db: Session, user: User):
    query = db.query(MetaPage)
    if user.is_platform_admin():
        # 平台管理员明确允许跨租户查看；租户管理员仍由全局 ORM 过滤隔离。
        return query
    return query


@router.get("")
def list_pages(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    account_ids: Optional[list[str]] = Query(None, max_length=50),
):
    requested = list(dict.fromkeys(account_ids)) if isinstance(account_ids, list) else []
    if requested:
        from services.business_access import require_accounts
        from services.credential_resolver import CredentialResolver
        from services.meta.page_access import page_account_access_error
        require_accounts(db, current_user, requested)
        accounts = db.query(AdAccount).filter(AdAccount.id.in_(requested)).all()
        if len(accounts) != len(requested):
            raise HTTPException(404, "部分广告账户不存在或无权访问")
        db.info["meta_actor_id"] = current_user.id
        candidates = None
        for account in accounts:
            try:
                ref = CredentialResolver(db).for_account(account.id, actor_id=current_user.id)
            except ValueError:
                return []
            if ref.connection_id:
                ids = {g.asset_id for g in db.query(MetaConnectionAsset).filter_by(
                    connection_id=ref.connection_id, asset_type="PAGE", status="ACTIVE").all()}
            else:
                ids = {p.id for p in db.query(MetaPage).filter_by(connector_credential_id=ref.credential_id).all()}
            candidates = ids if candidates is None else candidates & ids
        query = db.query(MetaPage).filter(MetaPage.id.in_(candidates or set()))
        if status:
            query = query.filter(MetaPage.status == status)
        return [p.to_dict() for p in query.order_by(MetaPage.page_name).all()
                if all(page_account_access_error(p, a) is None for a in accounts)]
    if current_user.is_platform_admin():
        with bypass_tenant():
            query = db.query(MetaPage)
            if status:
                query = query.filter(MetaPage.status == status)
            return [item.to_dict() for item in query.order_by(MetaPage.page_name).all()]
    query = db.query(MetaPage)
    if status:
        query = query.filter(MetaPage.status == status)
    if not current_user.is_admin():
        from sqlalchemy import or_
        from services.meta_execution_access import delegated_assignments, HEALTHY_CONNECTIONS
        delegated = delegated_assignments(db, current_user)
        delegated_ids = []
        for assignment in delegated:
            from services.credential_resolver import CredentialResolver
            try:
                ref = CredentialResolver(db).for_account(assignment.account_id, actor_id=current_user.id)
                if ref.connection_id == assignment.execution_connection_id:
                    delegated_ids.append(ref.connection_id)
            except ValueError:
                continue
        own = [c.id for c in db.query(MetaConnection).filter(or_(
            MetaConnection.authorized_by_user_id == current_user.id, MetaConnection.id.in_(delegated_ids)),
            MetaConnection.status == "ACTIVE").all() if connection_health(c) in HEALTHY_CONNECTIONS]
        own_pages = db.query(MetaConnectionAsset.asset_id).filter(MetaConnectionAsset.connection_id.in_(own),
            MetaConnectionAsset.asset_type == "PAGE", MetaConnectionAsset.status == "ACTIVE")
        query = query.filter(MetaPage.id.in_(own_pages))
    return [item.to_dict() for item in query.order_by(MetaPage.page_name).all()]


@router.post("/sync-all")
def sync_all_pages(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Refresh Pages for every Connector credential visible to this tenant."""
    bm_query = db.query(MetaAccount).filter(MetaAccount.connector_credential_id.isnot(None))
    account_query = db.query(AdAccount).filter(AdAccount.connector_credential_id.isnot(None))
    page_query = db.query(MetaPage).filter(MetaPage.connector_credential_id.isnot(None))
    connection_query = db.query(MetaConnection).join(
        User, User.id == MetaConnection.authorized_by_user_id,
    ).filter(MetaConnection.access_mode == "connector", MetaConnection.status == "ACTIVE", User.is_active.is_(True))
    if current_user.is_platform_admin():
        with bypass_tenant():
            businesses = bm_query.all()
            ad_accounts = account_query.all()
            pages = page_query.all()
            connections = connection_query.all()
        targets = {
            (item.tenant_id, item.connector_credential_id)
            for item in [*businesses, *ad_accounts, *pages]
            if item.tenant_id and item.connector_credential_id
        }
    else:
        tenant_id = effective_tenant_id(current_user)
        businesses = bm_query.all()
        ad_accounts = account_query.all()
        pages = page_query.all()
        connections = connection_query.all()
        targets = {
            (tenant_id, item.connector_credential_id)
            for item in [*businesses, *ad_accounts, *pages]
            if item.connector_credential_id
        }

    targets.update(
        (row.tenant_id, row.credential_id) for row in connections
        if row.tenant_id and row.credential_id
        and connection_health(row) in {"ACTIVE", "EXPIRING", "EXPIRING_1_DAY"}
    )

    if not targets:
        raise HTTPException(
            status_code=400,
            detail="当前租户没有可用的海外 Connector 凭据，请先完成 Meta OAuth 并接入广告账户",
        )

    results = []
    for tenant_id, credential_id in sorted(targets):
        try:
            with tenant_scope(tenant_id):
                result = sync_connector_pages(db, tenant_id, credential_id)
                db.commit()
            results.append({"status": "SUCCESS", "tenant_id": tenant_id, **result})
        except FBConnectorError as exc:
            db.rollback()
            results.append({"status": "FAILED", "tenant_id": tenant_id, "credential_id": credential_id, "error": str(exc)})

    has_success = any(item["status"] == "SUCCESS" and item.get("count", 0) > 0 for item in results)
    has_failure = any(item["status"] == "FAILED" for item in results)
    conflicts = [
        {"tenant_id": item["tenant_id"], **conflict}
        for item in results
        for conflict in item.get("conflicts", [])
    ]
    has_conflicts = bool(conflicts)
    status = (
        "FAILED" if has_failure and not has_success and not has_conflicts
        else "PARTIAL_SUCCESS" if has_failure or has_conflicts
        else "SUCCESS"
    )
    return {
        "status": status,
        "count": sum(item.get("count", 0) for item in results),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "results": results,
    }


@router.post("/sync")
def sync_pages(
    credential_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    credential = None if settings.FB_ACCESS_MODE == "connector" else db.query(Credential).filter(Credential.id == credential_id).first()
    if settings.FB_ACCESS_MODE != "connector":
        if not credential:
            raise HTTPException(status_code=404, detail="凭据不存在")
        if credential.tenant_id != effective_tenant_id(current_user):
            raise HTTPException(status_code=404, detail="凭据不存在")
        if credential.status != CredentialStatus.ACTIVE.value or credential.is_expired():
            raise HTTPException(status_code=400, detail="凭据已失效，请重新授权")
    if settings.FB_ACCESS_MODE == "connector":
        if not credential_id:
            raise HTTPException(status_code=400, detail="Connector 凭据 ID 不能为空")
        if current_user.is_platform_admin():
            with bypass_tenant():
                owner = db.query(MetaAccount).filter(
                    MetaAccount.connector_credential_id == credential_id
                ).first()
                if not owner:
                    owner = db.query(AdAccount).filter(
                        AdAccount.connector_credential_id == credential_id
                    ).first()
        else:
            owner = db.query(MetaAccount).filter(
                MetaAccount.connector_credential_id == credential_id
            ).first()
            if not owner:
                owner = db.query(AdAccount).filter(
                    AdAccount.connector_credential_id == credential_id
                ).first()
        if not owner or not owner.tenant_id:
            raise HTTPException(status_code=404, detail="Connector 凭据不存在或不属于当前租户")
        try:
            with tenant_scope(owner.tenant_id):
                result = sync_connector_pages(
                    db, owner.tenant_id, credential_id, allow_rebind=True
                )
                db.commit()
            return {"task_id": None, "status": "SUCCESS", **result}
        except FBConnectorError as exc:
            db.rollback(); raise HTTPException(status_code=503, detail=str(exc)) from exc
    task = sync_meta_pages_task.delay(credential_id)
    return {"task_id": task.id, "credential_id": credential_id, "status": "QUEUED"}
