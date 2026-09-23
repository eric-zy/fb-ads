"""Meta Custom Audience 强制排除策略解析与快照。"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from models import MetaAudienceAsset, MetaAudienceExclusionPolicy

ALLOWED_REASON_CODES = {"LEGAL", "PRIVACY", "OPERATIONS", "BRAND_SAFETY", "LEGACY_MIGRATION"}


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def resolve_required_exclusions(db: Session, account_pk: str, *, now: datetime | None = None) -> dict:
    """返回账户当前生效策略；旧布尔标记作为迁移期兼容回退。"""
    now = now or datetime.utcnow()
    assets = db.query(MetaAudienceAsset).filter(MetaAudienceAsset.ad_account_id == account_pk).all()
    asset_by_id = {row.id: row for row in assets}
    all_policies = db.query(MetaAudienceExclusionPolicy).filter(
        MetaAudienceExclusionPolicy.ad_account_id == account_pk,
    ).all()
    policies = [row for row in all_policies if row.status == "ACTIVE"]
    selected: dict[str, MetaAudienceAsset] = {}
    policy_rows = []
    for policy in policies:
        if not policy.is_effective(now):
            continue
        asset = asset_by_id.get(policy.meta_audience_asset_id)
        if asset:
            selected[asset.meta_audience_id] = asset
            policy_rows.append(policy)

    # 旧版本数据尚未迁移时仍生效；一旦存在策略记录，以策略状态为准。
    policy_asset_ids = {row.meta_audience_asset_id for row in all_policies}
    for asset in assets:
        if asset.id not in policy_asset_ids and asset.is_required_exclusion:
            selected[asset.meta_audience_id] = asset

    audience_ids = sorted(selected)
    versions = [row.policy_version for row in policy_rows]
    version = max(versions) if versions else 0
    snapshot = {
        "account_id": account_pk,
        "policy_version": version,
        "required_excluded_audience_ids": audience_ids,
        "captured_at": now.isoformat(),
        "fail_closed": True,
    }
    snapshot["hash"] = _hash(snapshot)
    return {"snapshot": snapshot, "assets": [selected[key] for key in audience_ids], "policies": policy_rows}


def sync_policy_rows(
    db: Session,
    account_pk: str,
    audience_ids: Iterable[str],
    *,
    created_by: str | None = None,
    approved_by: str | None = None,
    reason_code: str = "LEGACY_MIGRATION",
    reason_note: str | None = None,
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> list[MetaAudienceExclusionPolicy]:
    """兼容旧接口地把选中的 Meta ID 写入策略表。"""
    reason_code = str(reason_code or "LEGACY_MIGRATION").strip().upper()
    if reason_code not in ALLOWED_REASON_CODES:
        raise ValueError(f"不支持的策略原因: {reason_code}")
    desired = {str(value).strip() for value in audience_ids if str(value).strip()}
    assets = db.query(MetaAudienceAsset).filter(MetaAudienceAsset.ad_account_id == account_pk).all()
    by_meta_id = {row.meta_audience_id: row for row in assets}
    unknown = sorted(desired - set(by_meta_id))
    if unknown:
        raise ValueError(f"未同步的受众: {', '.join(unknown)}")

    rows = db.query(MetaAudienceExclusionPolicy).filter(
        MetaAudienceExclusionPolicy.ad_account_id == account_pk,
    ).all()
    by_asset_id = {row.meta_audience_asset_id: row for row in rows}
    now = datetime.utcnow()
    for asset in assets:
        selected = asset.meta_audience_id in desired
        policy = by_asset_id.get(asset.id)
        is_new = policy is None
        if selected and policy is None:
            policy = MetaAudienceExclusionPolicy(
                id=uuid.uuid4().hex,
                ad_account_id=account_pk,
                meta_audience_asset_id=asset.id,
                meta_audience_id=asset.meta_audience_id,
                status="ACTIVE",
                reason_code=reason_code,
                reason_note=reason_note,
                effective_from=effective_from,
                effective_until=effective_until,
                created_by=created_by,
                approved_by=approved_by,
                policy_version=1,
            )
            db.add(policy)
            by_asset_id[asset.id] = policy
        if policy:
            changed = (
                (policy.status == "ACTIVE") != selected
                or policy.reason_code != reason_code
                or policy.reason_note != reason_note
                or policy.effective_from != effective_from
                or policy.effective_until != effective_until
            )
            if changed and not is_new:
                policy.policy_version = (policy.policy_version or 0) + 1
            policy.status = "ACTIVE" if selected else "REVOKED"
            policy.reason_code = reason_code
            policy.reason_note = reason_note
            policy.effective_from = effective_from
            policy.effective_until = effective_until
            policy.created_by = policy.created_by or created_by
            policy.approved_by = approved_by or policy.approved_by
            policy.revoked_at = None if selected else now
        asset.is_required_exclusion = selected
    db.flush()
    return [row for row in by_asset_id.values() if row.status == "ACTIVE"]
