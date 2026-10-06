import hashlib
from datetime import datetime

from models import AdAccount
from models.meta_instagram import MetaInstagramSnapshot
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient


class MetaInstagramSyncService:
    def __init__(self, db):
        self.db = db

    def _snapshot(self, account):
        snapshot = self.db.query(MetaInstagramSnapshot).filter(
            MetaInstagramSnapshot.tenant_id == account.tenant_id,
            MetaInstagramSnapshot.ad_account_id == account.id,
        ).first()
        if not snapshot:
            snapshot = MetaInstagramSnapshot(
                id=hashlib.sha256(f"{account.tenant_id}:{account.id}".encode()).hexdigest()[:32],
                tenant_id=account.tenant_id, ad_account_id=account.id, credential_id="", items=[],
            )
            self.db.add(snapshot)
        return snapshot

    def sync_account(self, account_pk: str) -> dict:
        account = self.db.query(AdAccount).filter(AdAccount.id == account_pk).first()
        if not account:
            raise ValueError("广告账户不存在")
        snapshot = self._snapshot(account)
        try:
            ref = CredentialResolver(self.db).for_account(account.id)
            payload = FBConnectorClient().list_instagram_accounts(account.account_id, ref.credential_id)
            rows = payload.get("items")
            if not isinstance(rows, list):
                raise ValueError("Connector 未返回完整的 Instagram 身份列表")
            # 只持久化允许的元数据，绝不保存远端 Token 或任意原始字段。
            cleaned = {}
            for row in rows:
                identity = str(row.get("id") or "").strip()
                if not identity.isascii() or not identity.isdigit() or len(identity) > 64:
                    raise ValueError("Connector 返回了无效的 Instagram 身份 ID")
                item = cleaned.setdefault(identity, {"id": identity, "username": str(row.get("username") or identity), "page_ids": []})
                item["page_ids"] = sorted(set(item["page_ids"]) | {str(value) for value in row.get("page_ids", [])})
            snapshot.items = list(cleaned.values())
            snapshot.credential_id = ref.credential_id
            snapshot.status = "HEALTHY"
            snapshot.last_sync_error = None
            snapshot.last_synced_at = datetime.utcnow()
            self.db.commit()
            return {"status": "SUCCESS", "account_pk": account.id, "count": len(snapshot.items)}
        except Exception:
            # 保留旧列表供查看，但阻断其继续投放；错误不包含远端凭据内容。
            # 只有数据库事务已失败时才回滚；远端读取失败没有修改旧快照，
            # 直接保存 ERROR，避免撤销调用方同一事务内的其他工作。
            if not self.db.is_active:
                self.db.rollback()
                snapshot = self._snapshot(account)
            snapshot.status = "ERROR"
            snapshot.last_sync_error = "Instagram 身份同步失败，请检查授权权限和 Connector 状态后重试"
            self.db.commit()
            raise
