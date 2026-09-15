"""统一广告账户池 API。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from core.tenant import effective_tenant_id
from models import User
from services.account_pool import AccountPoolService

router = APIRouter(prefix="/api/v1/account-pool", tags=["广告账户池"])


@router.get("")
def list_account_pool(
    include_unassigned: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    tenant_id = effective_tenant_id(current_user)
    user_id = None if current_user.is_admin() else current_user.id
    rows = AccountPoolService(db).list(tenant_id, user_id=user_id, include_unassigned=include_unassigned)
    if not include_unassigned:
        rows = [row for row in rows if not row["assigned"]]
    return {"items": rows, "total": len(rows)}
