"""广告账户服务（Meta 账号管理 V1 —— 文档 §19 / §21）

核心职责：

> 准确判断一个广告账户是否允许参与后续批量投放。

**判断规则必须由后端统一计算，前端不得自行拼接**（文档 §19）。
前端只需调用 `GET /api/v1/accounts/available-for-deployment` 拿结果。

判断条件（全部满足才可用）：
    BM.status = ACTIVE
    AND AdAccount.system_status = ACTIVE
    AND Connector 凭据已绑定
    AND Meta 侧账户状态允许投放

说明：payment_status 仅作为同步后的账单信息展示，不参与投放资格判定。
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import AdAccount, BusinessAssetAccess, MetaAccount, BusinessStatus, SystemStatus, User
from services.account_access import accessible_account_ids

# Meta 侧明确不可投放的账户状态。
# Graph API 的 account_status 返回数字字符串（1=ACTIVE / 2=DISABLED / 3=UNSETTLED ...），
# 但不同 API 版本也可能返回枚举名，这里两者都覆盖。
UNDEPLOYABLE_META_STATUS = {
    "2", "3", "7", "8", "9", "100", "101", "202",
    "DISABLED", "UNSETTLED", "PENDING_RISK_REVIEW", "PENDING_SETTLEMENT",
    "PENDING_CLOSURE", "CLOSED", "ANY_CLOSED", "IN_GRACE_PERIOD",
}


class AdAccountService:
    """广告账户可用性判定与查询"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 可用性判定
    # ------------------------------------------------------------------
    def check_available(self, account: AdAccount, *, allow_paused_debug: bool = False) -> Tuple[bool, str]:
        """判断单个账户是否可参与批量投放

        ``allow_paused_debug`` 保留用于兼容旧调用方，但不再影响判定。
        用户支付状态不是本系统的投放前置条件；实际投放失败由 Meta 返回结果
        和任务重试/失败记录处理。

        Returns:
            (是否可用, 原因)。可用时原因为 "ok"。
        """
        # 1) 系统侧是否允许
        if account.system_status != SystemStatus.ACTIVE.value:
            reason = account.system_status_reason or "管理员已禁用"
            return False, f"系统侧已禁用：{reason}"

        # 2) BM 账号校验；个人账号不要求 BM，但必须绑定 Connector 凭据。
        business: Optional[MetaAccount] = account.business
        if business and business.status != BusinessStatus.ACTIVE.value:
            return False, f"BM 状态为 {business.status}"

        # 3) 只认海外 Connector 凭据引用，不回退到国内凭据表或全局 Token。
        connector_credential_id = (
            account.connector_credential_id
            or (business.connector_credential_id if business else None)
        )
        if not connector_credential_id:
            return False, "账号未绑定海外 Connector 凭据"

        # 4) Meta 侧状态。投放属于写操作，未同步或未知状态必须安全拒绝，
        # 避免仅凭本地 system_status=ACTIVE 就向 Meta 创建对象。
        meta_status = (account.account_status or "").strip().upper()
        if not meta_status:
            return False, "尚未同步 Meta 账户状态"
        if meta_status in UNDEPLOYABLE_META_STATUS:
            return False, f"Meta 侧状态为 {account.account_status}"
        if meta_status not in {"1", "ACTIVE"}:
            return False, f"Meta 侧状态未知或不可投放：{account.account_status}"

        return True, "ok"

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_available(
        self,
        *,
        business_id: Optional[str] = None,
        include_reason: bool = False,
        user_id: Optional[str] = None,
        allow_paused_debug: bool = False,
    ) -> List[Dict]:
        """列出可参与批量投放的账户（含 BM / 凭据上下文，供投放模块直接使用）"""
        q = self.db.query(AdAccount)
        if business_id:
            q = q.join(BusinessAssetAccess, BusinessAssetAccess.asset_id == AdAccount.id).filter(
                BusinessAssetAccess.business_id == business_id,
                BusinessAssetAccess.asset_type == "AD_ACCOUNT",
                BusinessAssetAccess.status == "ACTIVE",
            )
        if user_id:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user and not user.is_admin():
                visible_ids = accessible_account_ids(self.db, user) or {"__no_accounts__"}
                q = q.filter(AdAccount.id.in_(visible_ids))

        result: List[Dict] = []
        for account in q.order_by(AdAccount.created_at.desc()).all():
            available, reason = self.check_available(account, allow_paused_debug=allow_paused_debug)
            if not available:
                continue

            business: Optional[MetaAccount] = account.business
            connector_credential_id = (
                account.connector_credential_id
                or (business.connector_credential_id if business else None)
            )

            item = {
                "id": account.id,
                "account_id": account.account_id,
                "account_name": account.account_name,
                "currency": account.currency,
                "timezone": account.timezone,
                "system_status": account.system_status,
                "account_status": account.account_status,
                "business": {
                    "id": business.id if business else None,
                    "name": business.name if business else None,
                    "business_id": business.business_id if business else None,
                },
                "credential": {
                    "id": connector_credential_id,
                    "status": "ACTIVE",
                    "is_expired": False,
                    "masked": None,
                },
                "payment_status": account.payment_status,
                "payment_source": account.payment_source,
                "payment_error_message": account.payment_error_message,
                "payment_checked_at": account.payment_checked_at.isoformat() if account.payment_checked_at else None,
            }
            if include_reason:
                item["available_reason"] = reason
            result.append(item)

        return result

    def filter_available_ids(self, ad_account_ids: List[str], user_id: Optional[str] = None, *, allow_paused_debug: bool = False) -> Tuple[List[str], List[Dict]]:
        """从给定账户 ID 中筛出可投放的，返回 (可用 ID 列表, 被剔除的原因列表)

        供 JobService 在创建批量任务前做前置校验。
        """
        available_ids: List[str] = []
        rejected: List[Dict] = []

        for pk in ad_account_ids:
            account = self.db.query(AdAccount).filter(AdAccount.id == pk).first()
            if not account:
                rejected.append({"account_id": pk, "reason": "账户不存在"})
                continue
            if user_id:
                user = self.db.query(User).filter(User.id == user_id).first()
                if user and not user.is_admin():
                    visible_ids = accessible_account_ids(self.db, user) or set()
                    if account.id not in visible_ids:
                        rejected.append({"account_id": account.account_id, "reason": "账户未分配给当前用户"})
                        continue
            ok, reason = self.check_available(account, allow_paused_debug=allow_paused_debug)
            if ok:
                available_ids.append(pk)
            else:
                rejected.append({"account_id": account.account_id, "reason": reason})

        return available_ids, rejected
