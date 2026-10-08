"""Instagram 参数继承及本地授权校验，供模板、预检和 Worker 共用。"""
from datetime import datetime, timedelta

from models.meta_instagram import MetaInstagramSnapshot
from models import MetaPage
from services.meta.page_access import account_connector_credential_id, page_account_access_error


def instagram_user_id(config: dict) -> str:
    if any(config.get(key) and not str(config[key]).strip() for key in ("instagram_user_id", "instagram_actor_id")):
        raise ValueError("Instagram 身份不能为空白字符")
    modern = str(config.get("instagram_user_id") or "").strip()
    legacy = str(config.get("instagram_actor_id") or "").strip()
    if modern and legacy and modern != legacy:
        raise ValueError("Instagram 新旧身份字段不一致，请重新选择身份")
    value = modern or legacy
    if value and (not value.isascii() or not value.isdigit() or len(value) > 64):
        raise ValueError("Instagram 身份必须是有效的数字 ID")
    return value


def instagram_references(config: dict) -> list[tuple[str, str]]:
    """与 Connector Builder 的根配置 → 广告组 → 创意继承顺序一致。"""
    root_id = instagram_user_id(config)
    references = set()
    for adset in config.get("adsets") or [{}]:
        group_id = instagram_user_id(adset) or root_id
        page_id = str(adset.get("page_id") or config.get("page_id") or "")
        creatives = [config] if config.get("creative_format") == "CAROUSEL" else (
            adset.get("creatives") or config.get("creatives") or [config]
        )
        for creative in creatives:
            identity = group_id if creative is config else instagram_user_id(creative) or group_id
            if identity:
                references.add((page_id, identity))
    return sorted(references)


def snapshot_health(snapshot, account, now=None) -> str:
    if not snapshot:
        return "NEVER"
    if snapshot.status == "ERROR" or snapshot.last_sync_error:
        return "ERROR"
    if snapshot.credential_id != account_connector_credential_id(account):
        return "AUTH_CHANGED"
    if not snapshot.last_synced_at or snapshot.last_synced_at < (now or datetime.utcnow()) - timedelta(hours=24):
        return "STALE"
    return "HEALTHY"


def instagram_account_access_error(db, account, config: dict) -> str | None:
    references = instagram_references(config)
    if not references:
        return None
    from models import MetaConnectionAsset
    if db.query(MetaConnectionAsset.id).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).first():
        from services.credential_resolver import CredentialResolver
        try:
            ref = CredentialResolver(db).for_account(account.id)
        except ValueError as exc:
            return str(exc)
        grant = db.query(MetaConnectionAsset).filter_by(connection_id=ref.connection_id, asset_type="INSTAGRAM", asset_id=account.id, status="ACTIVE").first()
        if not grant or not grant.last_synced_at or grant.last_synced_at < datetime.utcnow() - timedelta(hours=24):
            return "当前执行授权的 Instagram 身份未同步或已过期，请同步我的 Meta 授权"
        for page_id, identity in references:
            page = db.query(MetaPage).filter_by(page_id=page_id).first()
            if not page or page_account_access_error(page, account):
                return "当前执行授权没有 Instagram 关联 Page 的投放权限"
            if not any(str(item.get("id")) == identity and page_id in item.get("page_ids", []) for item in grant.tasks or []):
                return f"当前执行授权无权使用 Instagram 身份 {identity}"
        return None
    snapshot = db.query(MetaInstagramSnapshot).filter(
        MetaInstagramSnapshot.tenant_id == account.tenant_id,
        MetaInstagramSnapshot.ad_account_id == account.id,
    ).first()
    health = snapshot_health(snapshot, account)
    if health != "HEALTHY":
        return f"Instagram 身份快照不可用（{health}），请同步目标账户的 Instagram 身份"
    for page_id, identity in references:
        page = db.query(MetaPage).filter(MetaPage.tenant_id == account.tenant_id, MetaPage.page_id == page_id, MetaPage.status == "ACTIVE").first()
        if not page or page_account_access_error(page, account):
            return f"Instagram 身份关联的 Facebook Page {page_id} 无广告投放权限"
        if not any(str(item.get("id")) == identity and page_id in item.get("page_ids", []) for item in snapshot.items or []):
            return f"Instagram 身份 {identity} 未授权给当前广告账户或未关联所选 Facebook Page {page_id}"
    return None
