"""投放前 Facebook Page 与广告账户授权关系校验。"""
from typing import Optional

from models import AdAccount, MetaPage, MetaConnectionAsset
from sqlalchemy.orm import object_session


ADVERTISING_PAGE_TASKS = {
    "ADVERTISE",
    "PROFILE_PLUS_ADVERTISE",
    "MANAGE",
    "PROFILE_PLUS_FULL_CONTROL",
}


def account_connection_id(account: AdAccount) -> Optional[str]:
    if account.connection_id:
        return account.connection_id
    if account.business and account.business.connection_id:
        return account.business.connection_id
    return None


def account_connector_credential_id(account: AdAccount) -> Optional[str]:
    """返回账户实际使用的 Connector 凭据 ID（Connector 模式）。"""
    # 与 CredentialResolver 保持同一优先级：账户级绑定代表本次实际授权，
    # BM 级绑定只作为历史数据/共享账户的回退，避免重新授权后被旧 BM 凭据覆盖。
    if account.connector_credential_id:
        return account.connector_credential_id
    if account.business and account.business.connector_credential_id:
        return account.business.connector_credential_id
    return None


def page_account_access_error(page: MetaPage, account: AdAccount) -> Optional[str]:
    """返回不可用于投放的原因；可用时返回 None。"""
    # 海外 Connector 不创建本地 OAuth connection，Page 与广告账户通过
    # connector_credential_id 绑定；旧逻辑访问 account.credential 会直接 500，
    # 因为 AdAccount 已没有 credential relationship。
    db = object_session(account) if isinstance(account, AdAccount) else None
    if db and db.query(MetaConnectionAsset.id).filter_by(asset_type="AD_ACCOUNT", asset_id=account.id).first():
        from services.credential_resolver import CredentialResolver
        try:
            ref = CredentialResolver(db).for_account(account.id)
        except ValueError as exc:
            return str(exc)
        grant = db.query(MetaConnectionAsset).filter_by(connection_id=ref.connection_id, asset_type="PAGE", asset_id=page.id, status="ACTIVE").first()
        if not grant:
            return "当前执行授权没有该 Page 的访问关系，请用同一个 Meta 个号同步账户和 Page"
        if not {str(x).upper() for x in grant.tasks or []}.intersection(ADVERTISING_PAGE_TASKS):
            return "当前执行授权没有该 Page 的广告投放权限（ADVERTISE）"
        return None
    page_connector = page.connector_credential_id
    account_connector = account_connector_credential_id(account)
    if page_connector or account_connector:
        page_status = getattr(page, "status", "ACTIVE")
        if page_connector and page_status != "ACTIVE":
            return f"Facebook Page 的 Connector 凭据状态为 {page_status}，请重新授权或同步"
        account_status = (getattr(account, "capabilities", None) or {}).get("connector_credential_status")
        if account_connector and account_status and account_status != "ACTIVE":
            return f"广告账户的 Connector 凭据状态为 {account_status}，请重新授权或同步"
        if not page_connector or not account_connector:
            return "页面或广告账户缺少 Connector 授权凭据，请重新同步授权资产"
        if page_connector != account_connector:
            return "页面与广告账户不属于同一个 Connector 授权凭据"
    else:
        page_connection = page.connection_id
        ad_connection = account_connection_id(account)
        if not page_connection or not ad_connection:
            return "页面或广告账户缺少 OAuth 授权连接，请重新同步授权资产"
        if page_connection != ad_connection:
            return "页面与广告账户不属于同一个 OAuth 授权连接"

    tasks = {str(task).upper() for task in (page.tasks or [])}
    if not tasks.intersection(ADVERTISING_PAGE_TASKS):
        return "当前授权没有该 Facebook Page 的广告投放权限（ADVERTISE）"
    return None
