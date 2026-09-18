"""统一广告账户池查询。

这里只负责聚合和过滤，不负责分配；后续调度器可复用同一套可用性规则。
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime

from config.settings import settings
from models import AdAccount, BusinessAssetAccess, Credential, MetaAccount, User, UserAccount
from services.account_access import accessible_account_ids


class AccountPoolService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id: str, user_id: str | None = None, include_unassigned: bool = True):
        base_filters = (
            AdAccount.tenant_id == tenant_id,
            BusinessAssetAccess.tenant_id == tenant_id,
            BusinessAssetAccess.asset_type == "AD_ACCOUNT",
            BusinessAssetAccess.status == "ACTIVE",
            MetaAccount.status == "ACTIVE",
            AdAccount.system_status == "ACTIVE",
        )
        if settings.FB_ACCESS_MODE == "connector":
            q = (
                self.db.query(AdAccount, MetaAccount, BusinessAssetAccess)
                .join(BusinessAssetAccess, BusinessAssetAccess.asset_id == AdAccount.id)
                .join(MetaAccount, MetaAccount.id == BusinessAssetAccess.business_id)
                .filter(*base_filters, MetaAccount.connector_credential_id.isnot(None))
            )
        else:
            q = (
                self.db.query(AdAccount, MetaAccount, BusinessAssetAccess, Credential)
                .join(BusinessAssetAccess, BusinessAssetAccess.asset_id == AdAccount.id)
                .join(MetaAccount, MetaAccount.id == BusinessAssetAccess.business_id)
                .outerjoin(Credential, Credential.id == BusinessAssetAccess.credential_id)
                .filter(*base_filters, or_(Credential.id.is_(None), Credential.status == "ACTIVE"))
            )
        if user_id:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user and not user.is_admin():
                visible_ids = accessible_account_ids(self.db, user) or {"__no_accounts__"}
                q = q.filter(AdAccount.id.in_(visible_ids))
        rows = []
        for row in q.order_by(AdAccount.account_name.asc()).all():
            account, bm, access = row[:3]
            credential = row[3] if settings.FB_ACCESS_MODE != "connector" else None
            if credential is None and settings.FB_ACCESS_MODE != "connector":
                credential = self.db.query(Credential).filter(
                    Credential.meta_account_id == bm.id,
                    Credential.status == "ACTIVE",
                ).order_by(Credential.updated_at.desc()).first()
            connector_credential_id = bm.connector_credential_id if settings.FB_ACCESS_MODE == "connector" else None
            assigned = self.db.query(UserAccount).filter(
                UserAccount.tenant_id == tenant_id,
                UserAccount.account_id == account.id,
                UserAccount.assignment_status == "ACTIVE",
                or_(UserAccount.expires_at.is_(None), UserAccount.expires_at > datetime.utcnow()),
            ).all()
            rows.append({
                "account_id": account.id,
                "meta_account_id": account.account_id,
                "account_name": account.account_name,
                "meta_status": account.effective_status or account.account_status,
                "system_status": account.system_status,
                "currency": account.currency,
                "timezone": account.timezone,
                "bm": {"id": bm.id, "business_id": bm.business_id, "name": bm.name},
                "access": {"id": access.id, "source": access.access_source, "level": access.access_level,
                           "credential_id": connector_credential_id or access.credential_id},
                "assigned_user_ids": [row.user_id for row in assigned],
                "assigned": bool(assigned),
                "pool_usable": bool(connector_credential_id) if settings.FB_ACCESS_MODE == "connector" else bool(credential and not credential.is_expired()),
            })
        return rows
