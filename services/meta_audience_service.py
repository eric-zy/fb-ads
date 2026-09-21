"""Meta Custom Audience 元数据同步服务。"""

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from config.settings import settings
from models import AdAccount, MetaAudienceAsset
from services.credential_service import CredentialService
from services.fb_connector_client import FBConnectorClient
from services.meta import MetaClient


def _items(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if data is None and isinstance(payload, dict):
        data = payload.get("audiences")
    return data if isinstance(data, list) else []


class MetaAudienceSyncService:
    """按广告账户同步 Custom Audience 元数据，不读取成员数据。"""

    def __init__(self, db: Session):
        self.db = db

    def sync_account(self, account_pk: str) -> dict:
        account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
        if not account:
            raise ValueError("广告账户不存在")

        connector_credential_id = account.connector_credential_id or (
            account.business.connector_credential_id if account.business else None
        )
        if settings.FB_ACCESS_MODE == "connector":
            if not connector_credential_id:
                raise ValueError("广告账户未绑定 Connector 凭据")
            payload = FBConnectorClient().list_custom_audiences(
                account.account_id,
                connector_credential_id,
            )
        else:
            token, _ = CredentialService(self.db).resolve_account_token(account_pk)
            payload = {"data": MetaClient(token).get_custom_audiences(account.account_id)}

        synced = []
        now = datetime.utcnow()
        for raw in _items(payload):
            audience_id = str(raw.get("id") or "").strip()
            if not audience_id:
                continue
            item = self.db.query(MetaAudienceAsset).filter(
                MetaAudienceAsset.ad_account_id == account.id,
                MetaAudienceAsset.meta_audience_id == audience_id,
            ).first()
            if not item:
                item = MetaAudienceAsset(
                    id=uuid.uuid4().hex,
                    ad_account_id=account.id,
                    meta_ad_account_id=account.account_id,
                    meta_audience_id=audience_id,
                    name=str(raw.get("name") or audience_id),
                )
                self.db.add(item)
            item.name = str(raw.get("name") or item.name or audience_id)
            item.subtype = raw.get("subtype")
            item.delivery_status = str(raw.get("delivery_status") or raw.get("operation_status") or "") or None
            item.sharing_status = str(raw.get("sharing_status") or "") or None
            item.last_synced_at = now
            item.last_sync_error = None
            synced.append(item)

        self.db.commit()
        return {
            "status": "SUCCESS",
            "account_pk": account_pk,
            "account_id": account.account_id,
            "count": len(synced),
            "items": [item.to_dict() for item in synced],
        }
