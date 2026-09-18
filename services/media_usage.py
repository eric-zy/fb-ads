"""素材使用事件的统一写入工具。"""
from typing import Any, Iterable, Optional
import uuid

from sqlalchemy.orm import Session

from models import CreativeAssetUsageEvent


def record_usage_event(
    db: Session,
    *,
    tenant_id: str,
    event_key: str,
    asset_id: str,
    status: str,
    event_type: str = "PUBLISH",
    publish_task_id: Optional[str] = None,
    published_ad_id: Optional[str] = None,
    ad_account_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    external_id: Optional[str] = None,
    error_message: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> CreativeAssetUsageEvent:
    """按事件键幂等写入或更新素材使用事件。"""
    event = db.query(CreativeAssetUsageEvent).filter(
        CreativeAssetUsageEvent.tenant_id == tenant_id,
        CreativeAssetUsageEvent.event_key == event_key,
    ).first()
    if not event:
        event = CreativeAssetUsageEvent(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            event_key=event_key,
            asset_id=asset_id,
            event_type=event_type,
            status=status,
            publish_task_id=publish_task_id,
            published_ad_id=published_ad_id,
            ad_account_id=ad_account_id,
            actor_id=actor_id,
            external_id=external_id,
            error_message=error_message,
            details=details,
        )
        db.add(event)
    else:
        event.status = status
        event.external_id = external_id or event.external_id
        event.error_message = error_message
        if details:
            event.details = {**(event.details or {}), **details}
    return event


def extract_asset_ids(config: Optional[dict]) -> list[str]:
    """从模板创意结构中提取去重后的素材 ID。"""
    if not isinstance(config, dict):
        return []
    values: list[str] = []
    creatives = config.get("creatives")
    if isinstance(creatives, list):
        values.extend(item.get("asset_id") for item in creatives if isinstance(item, dict))
    for adset in config.get("adsets") or []:
        if isinstance(adset, dict) and isinstance(adset.get("creatives"), list):
            values.extend(item.get("asset_id") for item in adset["creatives"] if isinstance(item, dict))
    cards = config.get("carousel_cards")
    if isinstance(cards, list):
        values.extend(item.get("asset_id") for item in cards if isinstance(item, dict))
    return list(dict.fromkeys(str(value) for value in values if value))


def record_template_usage(
    db: Session,
    *,
    tenant_id: str,
    event_key_prefix: str,
    asset_ids: Iterable[str],
    status: str,
    publish_task_id: Optional[str],
    ad_account_id: Optional[str],
    external_id: Optional[str] = None,
    error_message: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    for asset_id in dict.fromkeys(str(value) for value in asset_ids if value):
        record_usage_event(
            db,
            tenant_id=tenant_id,
            event_key=f"{event_key_prefix}:{asset_id}",
            asset_id=asset_id,
            status=status,
            publish_task_id=publish_task_id,
            ad_account_id=ad_account_id,
            external_id=external_id,
            error_message=error_message,
            details=details,
        )
