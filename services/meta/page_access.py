"""投放前 Facebook Page 与广告账户授权关系校验。"""
from typing import Optional

from models import AdAccount, MetaPage


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
    if account.credential and account.credential.connection_id:
        return account.credential.connection_id
    return None


def page_account_access_error(page: MetaPage, account: AdAccount) -> Optional[str]:
    """返回不可用于投放的原因；可用时返回 None。"""
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
