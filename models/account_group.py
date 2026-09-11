"""租户级广告账户组。"""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.orm import relationship
from core.database import Base
from core.tenant import TenantMixin

account_group_accounts = Table(
    "account_group_accounts", Base.metadata,
    Column("group_id", String(50), ForeignKey("account_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("account_id", String(50), ForeignKey("ad_accounts.id", ondelete="CASCADE"), primary_key=True),
)
account_group_users = Table(
    "account_group_users", Base.metadata,
    Column("group_id", String(50), ForeignKey("account_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", String(50), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

class AccountGroup(TenantMixin, Base):
    __tablename__ = "account_groups"
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    accounts = relationship("AdAccount", secondary=account_group_accounts, lazy="selectin")
    users = relationship("User", secondary=account_group_users, lazy="selectin")
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_account_groups_tenant_name"), Index("ix_account_groups_tenant", "tenant_id"))

    def to_dict(self):
        return {"id": self.id, "tenant_id": self.tenant_id, "name": self.name, "description": self.description,
                "account_count": len(self.accounts or []), "user_count": len(self.users or []),
                "account_ids": [a.id for a in self.accounts or []], "user_ids": [u.id for u in self.users or []]}
