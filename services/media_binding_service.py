"""素材到目标广告账户的按需绑定服务。

中央素材只保存一次；真正投放时，再为目标广告账户建立并派发账户级绑定。
这与 XMP 的素材库/渠道素材映射模型一致。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from models import AdAccount, CreativeAsset, MetaAssetBinding


def ensure_asset_bindings(
    db: Session,
    asset_ids: Iterable[str],
    ad_account_ids: Iterable[str],
) -> list[MetaAssetBinding]:
    """为指定账户幂等建立素材绑定，不调用外部平台。"""
    asset_ids = list(dict.fromkeys(str(value) for value in asset_ids if value))
    account_ids = list(dict.fromkeys(str(value) for value in ad_account_ids if value))
    if not asset_ids or not account_ids:
        return []

    assets = {
        asset.id: asset
        for asset in db.query(CreativeAsset).filter(CreativeAsset.id.in_(asset_ids)).all()
    }
    accounts = {
        account.id: account
        for account in db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()
    }
    bindings: list[MetaAssetBinding] = []
    for asset_id in asset_ids:
        asset = assets.get(asset_id)
        if not asset:
            continue
        for account_id in account_ids:
            account = accounts.get(account_id)
            if not account:
                continue
            binding = db.query(MetaAssetBinding).filter(
                MetaAssetBinding.asset_id == asset_id,
                MetaAssetBinding.ad_account_id == account_id,
            ).first()
            if not binding:
                binding = MetaAssetBinding(
                    id=uuid.uuid4().hex,
                    tenant_id=account.tenant_id,
                    asset_id=asset_id,
                    ad_account_id=account_id,
                    meta_asset_type=asset.asset_type,
                    status="PENDING",
                )
                db.add(binding)
            elif binding.status in ("FAILED", "EXPIRED"):
                binding.status = "PENDING"
                binding.error_message = None
                binding.error_code = None
                binding.connector_task_id = None
                binding.updated_at = datetime.utcnow()
            bindings.append(binding)
    db.flush()
    return bindings


def queue_pending_asset_bindings(bindings: Iterable[MetaAssetBinding]) -> list[dict[str, str]]:
    """派发尚未完成的绑定；READY/进行中的绑定保持幂等。"""
    from tasks.media_tasks import upload_asset_task

    queued = []
    for binding in bindings:
        if binding.status in ("PENDING", "FAILED", "EXPIRED") and not binding.meta_asset_id:
            task = upload_asset_task.delay(binding.id)
            queued.append({"binding_id": binding.id, "task_id": task.id})
    return queued
