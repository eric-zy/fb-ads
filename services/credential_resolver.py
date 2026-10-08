"""统一解析国内资产所引用的凭据类型。"""
from dataclasses import dataclass
from sqlalchemy.orm import Session
from models import AdAccount, Credential, MetaConnection, MetaConnectionAsset, User
from services.meta_connection_service import connection_health

@dataclass(frozen=True)
class CredentialRef:
    mode: str
    credential_id: str
    token: str | None = None
    connection_id: str | None = None
    version: int | None = None

class CredentialResolver:
    def __init__(self, db: Session):
        self.db = db

    def for_account(self, account_id: str, *, actor_id=None, connection_id=None) -> CredentialRef:
        """解析广告账户绑定的海外 Connector 凭据。"""
        account = self.db.query(AdAccount).filter(AdAccount.id == account_id).first()
        if not account:
            raise ValueError(f"广告账户不存在: {account_id}")
        actor_id = actor_id or self.db.info.get("meta_actor_id")
        connection_id = connection_id or self.db.info.get("meta_connection_id")
        grants = self.db.query(MetaConnectionAsset).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).all()
        if grants and not actor_id and not connection_id and not account.connection_id:
            legacy_id = account.connector_credential_id or (account.business.connector_credential_id if account.business else None)
            if legacy_id:
                # Retain the explicitly configured historical identity for system reads.
                return CredentialRef("connector", legacy_id)
        if grants:
            q = self.db.query(MetaConnection).filter(MetaConnection.id.in_([g.connection_id for g in grants if g.status == "ACTIVE"]))
            actor = self.db.query(User).filter_by(id=actor_id).first() if actor_id else None
            if actor and not connection_id:
                connection_id = (actor.settings or {}).get("meta_execution_connections", {}).get(account.id)
            if actor_id and (not actor or not actor.is_active):
                raise ValueError("操作人已停用或不存在")
            if connection_id:
                q = q.filter(MetaConnection.id == connection_id)
                if actor and not actor.is_admin():
                    q = q.filter(MetaConnection.authorized_by_user_id == actor_id)
            elif actor:
                q = q.filter(MetaConnection.authorized_by_user_id == actor_id)
            else:
                # Scheduled system reads use the established identity, never the latest person's token.
                q = q.filter(MetaConnection.id == account.connection_id)
            choices = [c for c in q.all() if connection_health(c) in {"ACTIVE", "EXPIRING", "EXPIRING_1_DAY"}]
            if not choices:
                raise ValueError("账户没有当前执行身份的有效 Meta 授权，请本人授权并同步账户")
            if len(choices) != 1:
                raise ValueError("该账户有多个个人授权，请明确选择执行授权")
            row = choices[0]
            owner = self.db.query(User).filter_by(id=row.authorized_by_user_id).first()
            if not owner or not owner.is_active:
                raise ValueError("Meta 授权所属用户已停用")
            token = None
            if row.access_mode == "direct":
                credential = self.db.query(Credential).filter_by(id=row.credential_id, connection_id=row.id, status="ACTIVE").first()
                if not credential or credential.is_expired():
                    raise ValueError("个人 Meta 凭据已失效")
                token = credential.get_access_token()
            return CredentialRef(row.access_mode, row.credential_id, token, row.id, row.version)
        if actor_id:
            actor = self.db.query(User).filter_by(id=actor_id).first()
            if not actor or not actor.is_active:
                raise ValueError("操作人已失效")
            if not actor.is_admin():
                raise ValueError("历史授权尚未确认归属，请在我的 Meta 授权中重新接入")
        if getattr(account, "connector_credential_id", None):
            return CredentialRef("connector", account.connector_credential_id)
        if account.business_id:
            meta = account.business
            if meta and getattr(meta, "connector_credential_id", None):
                return CredentialRef("connector", meta.connector_credential_id)
        raise ValueError(f"广告账户 {account_id} 未绑定海外 Connector 凭据")

    def for_job_item(self, item) -> CredentialRef:
        self.validate_snapshot(item.ad_account_id, item.authorization_connection_id)
        self.db.info["meta_actor_id"] = item.job.created_by
        self.db.info["meta_connection_id"] = item.authorization_connection_id
        ref = self.for_account(item.ad_account_id, actor_id=item.job.created_by,
                               connection_id=item.authorization_connection_id)
        if item.authorization_connection_id and ref.connection_id != item.authorization_connection_id:
            raise ValueError("任务授权身份已变更，请重新预检提交")
        # Same personal subject may refresh its token; the identity itself is immutable.
        return ref

    def validate_snapshot(self, account_id, connection_id):
        """Queued work predating personal ownership must be explicitly resubmitted."""
        if not connection_id and self.db.query(MetaConnectionAsset.id).filter_by(
            asset_type="AD_ACCOUNT", asset_id=account_id,
        ).first():
            raise ValueError("历史任务没有个人授权快照，请重新预检或重新提交操作")
