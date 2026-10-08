"""Import shared Meta assets without replacing another publisher's access."""
from datetime import datetime
import uuid
from models import AdAccount, MetaAccount, MetaConnectionAsset, UserAccount, Credential, BusinessAssetAccess
from services.meta_connection_service import grant_asset


def import_connection_accounts(db, connection, user, remote):
    imported = []
    for item in remote:
        business = item.get("business") or {}
        business_id = str(business.get("id") or "")
        meta = db.query(MetaAccount).filter_by(business_id=business_id).first() if business_id else None
        if not meta and business_id:
            meta = MetaAccount(id=uuid.uuid4().hex, tenant_id=connection.tenant_id,
                name=business.get("name") or business_id, business_id=business_id,
                app_id=connection.app_id, status="ACTIVE", sync_status="SUCCESS")
            db.add(meta)
            db.flush()
        if meta:
            grant_asset(db, connection, "BUSINESS", meta.id)
            # Keep explicitly established defaults. A second publisher does not take them over.
            if not meta.connection_id and not meta.connector_credential_id and not meta.default_credential_id:
                meta.connection_id = connection.id
                if connection.access_mode == "connector":
                    meta.connector_credential_id = connection.credential_id
            elif meta.connection_id == connection.id and connection.access_mode == "connector":
                meta.connector_credential_id = connection.credential_id
        account_id = str(item["id"])
        account = db.query(AdAccount).filter_by(account_id=account_id).first()
        is_new = account is None
        if is_new:
            account = AdAccount(id=uuid.uuid4().hex, tenant_id=connection.tenant_id,
                account_id=account_id, business_id=meta.id if meta else None,
                meta_business_id=business_id or None, owner_type="BUSINESS" if meta else "PERSONAL",
                system_status="ACTIVE", connection_id=connection.id)
            if connection.access_mode == "connector":
                account.connector_credential_id = connection.credential_id
            else:
                account.credential_id = connection.credential_id
            db.add(account)
            db.flush()
            db.add(UserAccount(id=uuid.uuid4().hex, tenant_id=connection.tenant_id,
                user_id=user.id, account_id=account.id, role="owner", assignment_role="PRIMARY",
                assignment_type="OAUTH", assignment_status="ACTIVE", assigned_by=user.id))
        account.account_name = item.get("name") or account_id
        account.account_status = str(item["account_status"]) if item.get("account_status") is not None else account.account_status
        account.currency = item.get("currency") or account.currency
        account.timezone = item.get("timezone_name") or account.timezone
        account.last_synced_at = datetime.utcnow()
        if account.connection_id == connection.id:
            if connection.access_mode == "connector":
                account.connector_credential_id = connection.credential_id
            else:
                account.credential_id = connection.credential_id
        grant_asset(db, connection, "AD_ACCOUNT", account.id)
        if meta and not db.query(BusinessAssetAccess.id).filter_by(business_id=meta.id, asset_type="AD_ACCOUNT", asset_id=account.id).first():
            db.add(BusinessAssetAccess(id=uuid.uuid4().hex, tenant_id=connection.tenant_id, business_id=meta.id,
                asset_type="AD_ACCOUNT", asset_id=account.id, access_level="MANAGE", access_source="OWNED", status="ACTIVE"))
        assignment = db.query(UserAccount).filter_by(user_id=user.id, account_id=account.id, assignment_status="ACTIVE").first()
        imported.append({"id": account.id, "account_id": account_id, "business_id": account.business_id,
            "business_name": meta.name if meta else None, "owner_type": account.owner_type,
            "assignment_required": not is_new and not user.is_admin() and not assignment})
    db.flush()
    return imported


def sync_connection_pages(db, connection):
    if connection.access_mode == "connector":
        from services.meta.connector_page_sync import sync_connector_pages
        result = sync_connector_pages(db, connection.tenant_id, connection.credential_id)
        db.commit()
        return result
    from services.meta.page_service import MetaPageSyncService
    return MetaPageSyncService(db).sync_credential(connection.credential_id)


def refresh_connection(db, connection, user):
    from services.fb_connector_client import FBConnectorClient
    from services.meta.oauth_service import MetaOAuthService
    from services.meta_connection_service import parse_expiry
    if connection.access_mode == "connector":
        client = FBConnectorClient()
        health = client.credential_health([connection.credential_id]).get("items", [])
        summary = next((x for x in health if x.get("id") == connection.credential_id), {})
        if summary.get("status") != "ACTIVE":
            connection.status = summary.get("status") or "INVALID"
            connection.last_error = summary.get("last_error") or "海外凭据已失效"
            db.commit()
            raise ValueError(connection.last_error)
        connection.expires_at = parse_expiry(summary.get("expires_at"))
        connection.scopes = summary.get("scopes") or []
        remote = client.oauth_ad_accounts(connection.credential_id).get("accounts", [])
    else:
        credential = db.query(Credential).filter_by(id=connection.credential_id, status="ACTIVE").first()
        if not credential or credential.is_expired():
            raise ValueError("个人 OAuth 凭据已失效，请重新授权")
        remote = MetaOAuthService().get_ad_accounts(credential.get_access_token())
    grants = db.query(MetaConnectionAsset).filter_by(connection_id=connection.id, asset_type="AD_ACCOUNT").all()
    local_ids = {x.asset_id for x in grants}
    accounts = db.query(AdAccount).filter(AdAccount.id.in_(local_ids)).all()
    wanted = {x.account_id for x in accounts}
    imported = import_connection_accounts(db, connection, user, [x for x in remote if str(x.get("id")) in wanted])
    seen = {x["id"] for x in imported}
    for grant in grants:
        if grant.asset_id not in seen:
            grant.status = "REVOKED"
    db.commit()
    pages = sync_connection_pages(db, connection)
    secondary_errors = []
    if connection.access_mode == "connector":
        from services.meta_tracking_asset_service import MetaTrackingAssetSyncService
        from services.meta_instagram_service import MetaInstagramSyncService
        db.info["meta_actor_id"] = user.id
        db.info["meta_connection_id"] = connection.id
        for item in imported:
            for service, label in ((MetaTrackingAssetSyncService, "Pixel / Dataset"), (MetaInstagramSyncService, "Instagram")):
                try:
                    service(db).sync_account(item["id"])
                except Exception:
                    db.rollback()
                    if label == "Instagram":
                        affected = db.query(MetaConnectionAsset).filter_by(connection_id=connection.id, asset_type="INSTAGRAM", asset_id=item["id"]).all()
                    else:
                        from models import MetaTrackingAsset
                        local_ids = db.query(MetaTrackingAsset.id).filter_by(ad_account_id=item["id"])
                        affected = db.query(MetaConnectionAsset).filter(MetaConnectionAsset.connection_id == connection.id,
                            MetaConnectionAsset.asset_type == "TRACKING", MetaConnectionAsset.asset_id.in_(local_ids)).all()
                    for grant in affected:
                        grant.status = "INVALID"
                    secondary_errors.append({"account_id": item["id"], "asset_type": label, "error": "同步失败，请检查该个号的资产权限"})
    connection.last_synced_at = datetime.utcnow()
    connection.last_error = "部分资产同步失败，请检查个人 Meta 资产权限并重试" if secondary_errors else None
    db.commit()
    return {"accounts": len(imported), "pages": pages, "asset_errors": secondary_errors}
