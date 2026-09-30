"""Short-lived coordination leases for account-level operations."""

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import AccountOperationLease


class AccountOperationBusy(Exception):
    """Raised when another user currently holds the account lease."""

    def __init__(self, lease: AccountOperationLease):
        self.lease = lease
        super().__init__("该广告账户正在被其他投手操作，请稍后重试")


class AccountOperationLeaseService:
    DEFAULT_TTL_SECONDS = 90
    MIN_TTL_SECONDS = 15
    MAX_TTL_SECONDS = 300

    def __init__(self, db: Session):
        self.db = db

    @classmethod
    def _ttl(cls, ttl_seconds: int | None) -> int:
        value = cls.DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
        return max(cls.MIN_TTL_SECONDS, min(cls.MAX_TTL_SECONDS, value))

    @staticmethod
    def serialize(lease: AccountOperationLease | None) -> dict | None:
        if not lease:
            return None
        return {
            "id": lease.id,
            "account_id": lease.account_id,
            "holder_user_id": lease.holder_user_id,
            "operation_type": lease.operation_type,
            "lease_token": lease.lease_token,
            "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
            "created_at": lease.created_at.isoformat() if lease.created_at else None,
        }

    def get(self, tenant_id: str, account_id: str) -> AccountOperationLease | None:
        lease = self.db.query(AccountOperationLease).filter(
            AccountOperationLease.tenant_id == tenant_id,
            AccountOperationLease.account_id == account_id,
        ).first()
        if lease and lease.expires_at <= datetime.utcnow():
            return None
        return lease

    def invalid_accounts(
        self,
        tenant_id: str,
        account_ids: list[str],
        holder_user_id: str,
        operation_leases: dict[str, str] | None,
        operation_type: str,
    ) -> list[str]:
        """Return accounts whose submission lease is missing or does not match."""
        lease_map = operation_leases or {}
        invalid = []
        for account_id in sorted(set(account_ids)):
            token = lease_map.get(account_id)
            lease = self.get(tenant_id, account_id)
            if (
                not token
                or not lease
                or lease.holder_user_id != holder_user_id
                or lease.lease_token != token
                or lease.operation_type != operation_type
            ):
                invalid.append(account_id)
        return invalid

    def acquire(
        self,
        tenant_id: str,
        account_id: str,
        holder_user_id: str,
        operation_type: str,
        ttl_seconds: int | None = None,
    ) -> AccountOperationLease:
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self._ttl(ttl_seconds))
        lease = self.db.query(AccountOperationLease).filter(
            AccountOperationLease.tenant_id == tenant_id,
            AccountOperationLease.account_id == account_id,
        ).with_for_update().first()

        if lease and lease.expires_at > now and lease.holder_user_id != holder_user_id:
            raise AccountOperationBusy(lease)

        if lease:
            # 同一投手续租时复用 token，前端可以安全地在 finally 中释放。
            lease.holder_user_id = holder_user_id
            lease.operation_type = operation_type
            lease.expires_at = expires_at
        else:
            lease = AccountOperationLease(
                id=uuid.uuid4().hex,
                tenant_id=tenant_id,
                account_id=account_id,
                holder_user_id=holder_user_id,
                operation_type=operation_type,
                lease_token=secrets.token_urlsafe(32),
                expires_at=expires_at,
            )
            self.db.add(lease)
        self.db.flush()
        return lease

    def release(
        self,
        tenant_id: str,
        account_id: str,
        holder_user_id: str,
        lease_token: str,
    ) -> bool:
        lease = self.db.query(AccountOperationLease).filter(
            AccountOperationLease.tenant_id == tenant_id,
            AccountOperationLease.account_id == account_id,
            AccountOperationLease.holder_user_id == holder_user_id,
            AccountOperationLease.lease_token == lease_token,
        ).with_for_update().first()
        if not lease:
            return False
        self.db.delete(lease)
        self.db.flush()
        return True
