"""广告账户自动分配服务。"""
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from models import AdAccount, User, UserAccount, AccountAssignmentRule, AccountAssignmentLog, BusinessAssetAccess, MetaAccount
from services.account_pool import AccountPoolService


class AccountDispatchService:
    def __init__(self, db: Session):
        self.db = db

    def dispatch(self, tenant_id: str, account_id: str, operator_id: str | None = None):
        account = self.db.query(AdAccount).filter(AdAccount.id == account_id, AdAccount.tenant_id == tenant_id).with_for_update().first()
        if not account:
            raise ValueError("广告账户不存在")
        rules = self.db.query(AccountAssignmentRule).filter(
            AccountAssignmentRule.tenant_id == tenant_id,
            AccountAssignmentRule.status == "ACTIVE",
        ).order_by(AccountAssignmentRule.priority.asc()).all()
        for rule in rules:
            config = rule.rule_config or {}
            access = self.db.query(BusinessAssetAccess).filter(BusinessAssetAccess.asset_id == account_id, BusinessAssetAccess.tenant_id == tenant_id, BusinessAssetAccess.status == "ACTIVE").first()
            bm = self.db.query(MetaAccount).filter(MetaAccount.id == access.business_id).first() if access else None
            if config.get("business_id") and (not bm or bm.id != config["business_id"]):
                continue
            if config.get("currency") and account.currency != config["currency"]:
                continue
            if config.get("timezone") and account.timezone != config["timezone"]:
                continue
            tag = config.get("tag")
            if tag and tag not in (account.capabilities or {}).get("tags", []):
                continue
            user_ids = config.get("user_ids") or ([rule.target_user_id] if rule.target_user_id else [])
            users = self.db.query(User).filter(User.id.in_(user_ids), User.tenant_id == tenant_id, User.is_active == True).all() if user_ids else []
            if not users:
                continue
            counts = {u.id: self.db.query(UserAccount).filter(UserAccount.tenant_id == tenant_id, UserAccount.user_id == u.id, UserAccount.assignment_status == "ACTIVE").count() for u in users}
            user = sorted(users, key=lambda u: (counts[u.id], user_ids.index(u.id)))[0]
            existing = self.db.query(UserAccount).filter(UserAccount.tenant_id == tenant_id, UserAccount.account_id == account_id, UserAccount.assignment_status == "ACTIVE").first()
            if existing:
                return existing
            assignment = UserAccount(id=uuid.uuid4().hex, tenant_id=tenant_id, user_id=user.id, account_id=account_id, assignment_type="AUTO", assignment_status="ACTIVE", assigned_by=operator_id)
            self.db.add(assignment)
            self.db.add(AccountAssignmentLog(id=uuid.uuid4().hex, tenant_id=tenant_id, account_id=account_id, to_user_id=user.id, rule_id=rule.id, action="ASSIGN", operator_id=operator_id, reason="自动分配"))
            self.db.commit()
            return assignment
        raise ValueError("没有匹配的有效分配规则")

    def release(self, tenant_id: str, account_id: str, operator_id: str | None = None):
        rows = self.db.query(UserAccount).filter(UserAccount.tenant_id == tenant_id, UserAccount.account_id == account_id, UserAccount.assignment_status == "ACTIVE").all()
        for row in rows:
            row.assignment_status = "REVOKED"
            self.db.add(AccountAssignmentLog(id=uuid.uuid4().hex, tenant_id=tenant_id, account_id=account_id, from_user_id=row.user_id, action="RELEASE", operator_id=operator_id, reason="释放账户"))
        self.db.commit()
        return len(rows)
