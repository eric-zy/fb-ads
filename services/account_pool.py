"""统一广告账户池查询。

这里只负责聚合和过滤，不负责分配；后续调度器可复用同一套可用性规则。
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import AdAccount, BusinessAssetAccess, Credential, MetaAccount, UserAccount


class AccountPoolService:
    def __init__(self, db: Session):
        self.db = db

    def list(self, tenant_id: str, user_id: str | None = None, include_unassigned: bool = True):
        q = (
            self.db.query(AdAccount, MetaAccount, BusinessAssetAccess, Credential)
            .join(BusinessAssetAccess, BusinessAssetAccess.asset_id == AdAccount.id)
            .join(MetaAccount, MetaAccount.id == BusinessAssetAccess.business_id)
            .outerjoin(Credential, Credential.id == BusinessAssetAccess.credential_id)
            .filter(
                AdAccount.tenant_id == tenant_id,
                BusinessAssetAccess.tenant_id == tenant_id,
                BusinessAssetAccess.asset_type == "AD_ACCOUNT",
                BusinessAssetAccess.status == "ACTIVE",
                MetaAccount.status == "ACTIVE",
                AdAccount.system_status == "ACTIVE",
                or_(Credential.id.is_(None), Credential.status == "ACTIVE"),
            )
        )
        if user_id:
            q = q.join(UserAccount, UserAccount.account_id == AdAccount.id).filter(
                UserAccount.tenant_id == tenant_id, UserAccount.user_id == user_id
            )
        rows = []
        for account, bm, access, credential in q.order_by(AdAccount.account_name.asc()).all():
            if credential is None:
                credential = self.db.query(Credential).filter(
                    Credential.meta_account_id == bm.id,
                    Credential.status == "ACTIVE",
                ).order_by(Credential.updated_at.desc()).first()
            assigned = self.db.query(UserAccount).filter(
                UserAccount.tenant_id == tenant_id, UserAccount.account_id == account.id
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
                           "credential_id": access.credential_id},
                "assigned_user_ids": [row.user_id for row in assigned],
                "assigned": bool(assigned),
                "pool_usable": bool(credential and not credential.is_expired()) if credential else False,
            })
        return rows
