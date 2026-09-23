"""Meta Custom Audience 元数据同步服务。"""

from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from config.settings import settings
from models import AdAccount, MetaAudienceAsset, MetaAudienceExclusionPolicy, SyncAlert
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
        seen_ids = set()
        for raw in _items(payload):
            audience_id = str(raw.get("id") or "").strip()
            if not audience_id:
                continue
            seen_ids.add(audience_id)
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
            item.last_seen_at = now
            item.sync_status = "ACTIVE"
            item.meta_time_updated = _parse_meta_time(raw.get("time_updated"))
            item.last_sync_error = None
            synced.append(item)

        # 仅在 Connector/Meta 返回完整列表时标记缺失项；请求异常会在此之前抛出，
        # 不会误把全部受众置为 MISSING。
        existing = self.db.query(MetaAudienceAsset).filter(
            MetaAudienceAsset.ad_account_id == account.id,
        ).all()
        for item in existing:
            if item.meta_audience_id not in seen_ids:
                item.sync_status = "MISSING"
                item.last_synced_at = now

        self._update_policy_alerts(account, now)

        self.db.commit()
        return {
            "status": "SUCCESS",
            "account_pk": account_pk,
            "account_id": account.account_id,
            "count": len(synced),
            "items": [item.to_dict() for item in synced],
        }

    def _update_policy_alerts(self, account: AdAccount, now: datetime) -> None:
        policies = self.db.query(MetaAudienceExclusionPolicy).filter(
            MetaAudienceExclusionPolicy.ad_account_id == account.id,
            MetaAudienceExclusionPolicy.status == "ACTIVE",
        ).all()
        assets = {
            row.id: row
            for row in self.db.query(MetaAudienceAsset).filter(
                MetaAudienceAsset.ad_account_id == account.id,
            ).all()
        }
        blocked = []
        for policy in policies:
            asset = assets.get(policy.meta_audience_asset_id)
            if not asset or not policy.is_effective(now):
                continue
            delivery_status = str(asset.delivery_status or "").upper()
            if asset.sync_status in {"MISSING", "DELETED", "EXPIRED", "UNAVAILABLE"} or any(
                marker in delivery_status for marker in ("DELETED", "EXPIRED", "UNAVAILABLE")
            ):
                blocked.append(f"{asset.name}（{asset.meta_audience_id}）")

        open_alert = self.db.query(SyncAlert).filter(
            SyncAlert.ad_account_id == account.id,
            SyncAlert.alert_type == "META_AUDIENCE_POLICY",
            SyncAlert.is_resolved.is_(False),
        ).order_by(SyncAlert.created_at.desc()).first()
        if blocked:
            message = "强制排除受众不可用，相关账户发布将被阻断：" + ", ".join(blocked[:20])
            if open_alert:
                open_alert.message = message
            else:
                self.db.add(SyncAlert(
                    id=uuid.uuid4().hex,
                    tenant_id=account.tenant_id,
                    ad_account_id=account.id,
                    alert_type="META_AUDIENCE_POLICY",
                    title="Meta 强制排除受众异常",
                    message=message,
                ))
        elif open_alert:
            open_alert.is_resolved = True
            open_alert.resolved_at = now


def _parse_meta_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
