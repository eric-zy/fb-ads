from datetime import datetime
from models import UserAccount, AccountAssignmentLog
import uuid

def release_expired_assignments(db, tenant_id=None):
    q = db.query(UserAccount).filter(UserAccount.assignment_status == "ACTIVE", UserAccount.expires_at.isnot(None), UserAccount.expires_at <= datetime.utcnow())
    if tenant_id:
        q = q.filter(UserAccount.tenant_id == tenant_id)
    rows = q.all()
    for row in rows:
        row.assignment_status = "REVOKED"
        db.add(AccountAssignmentLog(id=uuid.uuid4().hex, tenant_id=row.tenant_id, account_id=row.account_id, from_user_id=row.user_id, action="EXPIRE", reason="分配已过期"))
    db.commit()
    return len(rows)
