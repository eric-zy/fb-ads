"""广告账户标识解析

==========================================================================
为什么需要这个模块
==========================================================================
系统里存在两种"广告账户 ID"，历史上被混用：

    1. 内部主键 `AdAccount.id`          —— 所有业务表外键都指向它
    2. Meta 账户号 `AdAccount.account_id` —— act_xxx，只有调 Meta API 时才需要

混用表现为同一个 `account_id` 参数在不同方法里被当成不同东西：

    RiskDetector.freeze_account       按 `account_id`（act_xxx）查
    RiskDetector.check_quality_score  按 `ad_account_id`（主键）查

结果取决于调用方传了什么，排查困难。

统一约定：
    - **业务层内部一律使用主键 `AdAccount.id`**
    - 仅在调用 `fb_client`（Meta API 边界）时转成 act_xxx
    - 面向外部/历史调用方的入口，用 `resolve_ad_account()` 做兼容解析

这样编排任务派发主键、API 沿用 act_xxx，两条路径都能正确工作。

用法：
    account = resolve_ad_account(db, account_ref)
    if not account:
        return 0
    # 调 Meta API
    fb_client.get_insights(account_id=account.account_id, ...)
    # 写业务表
    AccountInsight(ad_account_id=account.id, ...)
"""
from typing import Optional

from sqlalchemy.orm import Session

from core.logger import logger
from models import AdAccount


def resolve_ad_account(db: Session, account_ref: str) -> Optional[AdAccount]:
    """按主键或 Meta 账户号定位广告账户

    先按主键 `id` 匹配，落空再按 `account_id`(act_xxx) 兜底。
    都找不到返回 None，由调用方决定是报错还是跳过。
    """
    if not account_ref:
        return None

    account = db.query(AdAccount).filter(AdAccount.id == account_ref).first()
    if account:
        return account

    account = (
        db.query(AdAccount).filter(AdAccount.account_id == account_ref).first()
    )
    if account:
        logger.debug(
            f"[account-resolver] {account_ref} 按 Meta 账户号命中，"
            f"已归一到主键 {account.id}"
        )
    return account


def resolve_tenant_of_ad_account_ref(account_ref: str) -> Optional[str]:
    """供 Celery 任务使用：自己开 session 解析账户归属租户

    任务的 resolver 拿不到外部传入的 db，因此这里开一个短 session，
    查完立即关闭。与 `resolve_ad_account` 一样兼容主键与 act_xxx。
    """
    from core.database import SessionLocal
    from core.tenant import bypass_tenant

    db = SessionLocal()
    try:
        with bypass_tenant():
            account = resolve_ad_account(db, account_ref)
        return getattr(account, "tenant_id", None) if account else None
    except Exception as e:  # noqa: BLE001 - 解析失败不应让任务崩溃
        logger.warning(f"[account-resolver] 解析租户失败 {account_ref}: {e}")
        return None
    finally:
        db.close()
