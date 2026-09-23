"""账户级 Meta Custom Audience 强制排除策略。"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from core.database import Base
from core.tenant import TenantMixin


class MetaAudienceExclusionPolicy(TenantMixin, Base):
    """描述某个广告账户必须排除的 Meta Custom Audience。

    策略与 Meta 受众目录分离：目录是外部资产缓存，策略是 XMP 的
    法律/运营控制面。当前采用一条记录覆盖当前状态，变更通过版本和审计日志追踪。
    """

    __tablename__ = "meta_audience_exclusion_policies"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "meta_audience_asset_id", name="uq_meta_audience_policy_asset"),
        Index("ix_meta_audience_policy_tenant_account", "tenant_id", "ad_account_id"),
        Index("ix_meta_audience_policy_tenant_status", "tenant_id", "status"),
    )

    id = Column(String(50), primary_key=True, index=True)
    ad_account_id = Column(String(50), nullable=False, index=True, comment="系统广告账户主键")
    meta_audience_asset_id = Column(
        String(50), ForeignKey("meta_audience_assets.id"), nullable=False, index=True,
    )
    meta_audience_id = Column(String(128), nullable=False, index=True, comment="冗余 Meta Audience ID")
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    reason_code = Column(String(32), nullable=False, default="LEGACY_MIGRATION", server_default="LEGACY_MIGRATION")
    reason_note = Column(Text, nullable=True)
    effective_from = Column(DateTime, nullable=True)
    effective_until = Column(DateTime, nullable=True)
    policy_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_by = Column(String(50), nullable=True)
    approved_by = Column(String(50), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def is_effective(self, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        return (
            self.status == "ACTIVE"
            and (self.effective_from is None or self.effective_from <= now)
            and (self.effective_until is None or self.effective_until > now)
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ad_account_id": self.ad_account_id,
            "meta_audience_asset_id": self.meta_audience_asset_id,
            "meta_audience_id": self.meta_audience_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_note": self.reason_note,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_until": self.effective_until.isoformat() if self.effective_until else None,
            "policy_version": self.policy_version,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
