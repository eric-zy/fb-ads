"""广告账户主键解析。

业务层统一传递 ``AdAccount.id``；只有到 Meta API 边界时才使用
``AdAccount.account_id``（act_xxx）。这样可以避免同一个参数在不同层
被解释成两种 ID。
"""
from typing import Optional

from sqlalchemy.orm import Session

from models import AdAccount


def resolve_ad_account(db: Session, account_id: str) -> Optional[AdAccount]:
    """按内部主键定位广告账户。"""
    if not account_id:
        return None
    return db.query(AdAccount).filter(AdAccount.id == account_id).first()


def resolve_tenant_of_ad_account_ref(account_id: str) -> Optional[str]:
    """供 Celery 任务使用：解析内部账户主键归属租户。"""
    from core.database import SessionLocal
    from core.tenant import bypass_tenant

    db = SessionLocal()
    try:
        with bypass_tenant():
            account = resolve_ad_account(db, account_id)
        return getattr(account, "tenant_id", None) if account else None
    except Exception:  # noqa: BLE001 - 解析失败不应让任务崩溃
        return None
    finally:
        db.close()
