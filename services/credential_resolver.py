"""统一解析国内资产所引用的凭据类型。"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from models import AdAccount

@dataclass(frozen=True)
class CredentialRef:
    mode: str
    credential_id: str
    token: str | None = None

class CredentialResolver:
    def __init__(self, db: Session):
        self.db = db

    def for_account(self, account_id: str) -> CredentialRef:
        """解析广告账户绑定的海外 Connector 凭据。"""
        account = self.db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            raise ValueError(f"广告账户不存在: {account_id}")
        if getattr(account, "connector_credential_id", None):
            return CredentialRef("connector", account.connector_credential_id)
        if account.business_id:
            meta = account.business
            if meta and getattr(meta, "connector_credential_id", None):
                return CredentialRef("connector", meta.connector_credential_id)
        raise ValueError(f"广告账户 {account_id} 未绑定海外 Connector 凭据")
