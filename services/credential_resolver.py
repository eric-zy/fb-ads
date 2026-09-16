"""统一解析国内资产所引用的凭据类型。"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from models import AdAccount, MetaAccount, Credential
from core.enums import CredentialStatus

@dataclass(frozen=True)
class CredentialRef:
    mode: str
    credential_id: str
    token: str | None = None

class CredentialResolver:
    def __init__(self, db: Session):
        self.db = db

    def for_account(self, account_id: str) -> CredentialRef:
        account = self.db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            raise ValueError(f"广告账户不存在: {account_id}")
        if getattr(account, "connector_credential_id", None):
            return CredentialRef("connector", account.connector_credential_id)
        if account.credential_id:
            cred = self.db.query(Credential).filter(Credential.id == account.credential_id, Credential.status == CredentialStatus.ACTIVE.value).first()
            if cred and not cred.is_expired():
                return CredentialRef("direct", cred.id, cred.get_access_token())
        if account.business_id:
            meta = self.db.query(MetaAccount).filter(MetaAccount.id == account.business_id).first()
            if meta and getattr(meta, "connector_credential_id", None):
                return CredentialRef("connector", meta.connector_credential_id)
            if meta and meta.default_credential_id:
                cred = self.db.query(Credential).filter(Credential.id == meta.default_credential_id, Credential.status == CredentialStatus.ACTIVE.value).first()
                if cred and not cred.is_expired():
                    return CredentialRef("direct", cred.id, cred.get_access_token())
        raise ValueError(f"广告账户 {account_id} 无可用凭据")
