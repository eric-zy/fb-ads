from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from config.settings import settings
from models import AdAccount, MetaTrackingAsset
from services.credential_service import CredentialService
from services.fb_connector_client import FBConnectorClient
from services.meta import MetaClient


class MetaTrackingAssetSyncService:
    """同步单个广告账户的 Pixel / Dataset 元数据。"""

    def __init__(self, db: Session):
        self.db = db

    def sync_account(self, account_pk: str) -> dict:
        account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
        if not account:
            raise ValueError("广告账户不存在")

        if settings.FB_ACCESS_MODE == "connector":
            from services.credential_resolver import CredentialResolver
            credential_id = CredentialResolver(self.db).for_account(account.id).credential_id
            if not credential_id:
                raise ValueError("广告账户未绑定 Connector 凭据")
            payload = FBConnectorClient().list_tracking_assets(account.account_id, credential_id)
            rows = payload.get("assets", payload.get("data", []))
        else:
            token, _ = CredentialService(self.db).resolve_account_token(account_pk)
            rows = MetaClient(token).get_tracking_assets(account.account_id, account.meta_business_id)

        now = datetime.utcnow()
        from models import MetaConnection, MetaConnectionAsset
        from services.meta_connection_service import grant_asset
        connection = None
        if self.db.query(MetaConnectionAsset.id).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).first():
            from services.credential_resolver import CredentialResolver
            ref = CredentialResolver(self.db).for_account(account.id)
            connection = self.db.query(MetaConnection).filter_by(id=ref.connection_id).one()
        seen: set[tuple[str, str]] = set()
        synced: list[MetaTrackingAsset] = []
        for raw in rows if isinstance(rows, list) else []:
            asset_id = str(raw.get("id") or "").strip()
            asset_type = str(raw.get("asset_type") or raw.get("type") or "PIXEL").upper()
            if not asset_id or asset_type not in {"PIXEL", "DATASET"}:
                continue
            key = (asset_id, asset_type)
            seen.add(key)
            item = self.db.query(MetaTrackingAsset).filter(
                MetaTrackingAsset.ad_account_id == account.id,
                MetaTrackingAsset.meta_asset_id == asset_id,
                MetaTrackingAsset.asset_type == asset_type,
            ).first()
            if not item:
                item = MetaTrackingAsset(
                    id=uuid.uuid4().hex,
                    ad_account_id=account.id,
                    meta_ad_account_id=account.account_id,
                    meta_asset_id=asset_id,
                    asset_type=asset_type,
                    name=str(raw.get("name") or asset_id),
                )
                self.db.add(item)
            item.name = str(raw.get("name") or item.name or asset_id)
            item.status = "ACTIVE"
            item.usable = True
            item.last_synced_at = now
            item.last_sync_error = None
            item.raw_json = raw
            synced.append(item)
            self.db.flush()
            if connection:
                grant_asset(self.db, connection, "TRACKING", item.id)

        # Meta 删除/撤销授权后不再出现在列表中，保留记录便于审计，
        # 但发布页不会再把它当作可用资产返回。
        existing = self.db.query(MetaTrackingAsset).filter(
            MetaTrackingAsset.ad_account_id == account.id,
        ).all()
        for item in existing:
            if (item.meta_asset_id, item.asset_type) not in seen:
                if connection:
                    grant = self.db.query(MetaConnectionAsset).filter_by(connection_id=connection.id, asset_type="TRACKING", asset_id=item.id).first()
                    if grant:
                        grant.status = "REVOKED"
                    continue
                item.status = "UNAVAILABLE"
                item.usable = False
                item.last_synced_at = now

        self.db.commit()
        return {
            "status": "SUCCESS",
            "account_pk": account.id,
            "account_id": account.account_id,
            "count": len(synced),
            "items": [item.to_dict() for item in synced],
            "synced_at": now.isoformat(),
        }
