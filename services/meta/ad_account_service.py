"""广告账户服务（Meta 账号管理 V1 —— 文档 §19 / §21）

核心职责：

> 准确判断一个广告账户是否允许参与后续批量投放。

**判断规则必须由后端统一计算，前端不得自行拼接**（文档 §19）。
前端只需调用 `GET /api/v1/accounts/available-for-deployment` 拿结果。

判断条件（全部满足才可用）：
    BM.status = ACTIVE
    AND AdAccount.system_status = ACTIVE
    AND Credential.status = ACTIVE 且未过期
    AND Meta 侧账户状态允许投放
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from core.enums import CredentialStatus
from models import AdAccount, MetaAccount, BusinessStatus, SystemStatus


def _credential_service(db):
    """延迟导入，避免与 services.credential_service 形成循环导入

    credential_service 依赖 services.meta（MetaClient），而本模块又被
    services/meta/__init__.py 导出，顶层直接 import 会构成环。
    """
    from services.credential_service import CredentialService

    return CredentialService(db)

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
    def check_available(self, account: AdAccount) -> Tuple[bool, str]:
        """判断单个账户是否可参与批量投放

        Returns:
            (是否可用, 原因)。可用时原因为 "ok"。
        """
        # 1) 系统侧是否允许
        if account.system_status != SystemStatus.ACTIVE.value:
            reason = account.system_status_reason or "管理员已禁用"
            return False, f"系统侧已禁用：{reason}"

        # 2) 归属 BM 是否存在且启用
        business: Optional[MetaAccount] = account.business
        if not business:
            return False, "未归属任何 BM"
        if business.status != BusinessStatus.ACTIVE.value:
            return False, f"BM 状态为 {business.status}"

        # 3) 凭据是否可用（加密凭据表，过期视为不可用）
        cred = _credential_service(self.db).get_meta_credential(business.id)
        if not cred:
            return False, "BM 无可用凭据"
        if cred.status != CredentialStatus.ACTIVE.value:
            return False, f"凭据状态为 {cred.status}"
        if cred.is_expired():
            return False, "凭据已过期"

        # 4) Meta 侧状态（未同步时 account_status 为空，按宽容处理放行）
        meta_status = (account.account_status or "").strip().upper()
        if meta_status and meta_status in UNDEPLOYABLE_META_STATUS:
            return False, f"Meta 侧状态为 {account.account_status}"

        return True, "ok"

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_available(
        self,
        *,
        business_id: Optional[str] = None,
        include_reason: bool = False,
    ) -> List[Dict]:
        """列出可参与批量投放的账户（含 BM / 凭据上下文，供投放模块直接使用）"""
        q = self.db.query(AdAccount)
        if business_id:
            q = q.filter(AdAccount.business_id == business_id)

        result: List[Dict] = []
        for account in q.order_by(AdAccount.created_at.desc()).all():
            available, reason = self.check_available(account)
            if not available:
                continue

            business: Optional[MetaAccount] = account.business
            cred = (
                _credential_service(self.db).get_meta_credential(business.id)
                if business
                else None
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
                    "id": cred.id if cred else None,
                    "status": cred.status if cred else None,
                    "is_expired": cred.is_expired() if cred else None,
                    # 脱敏，绝不明文返回
                    "masked": (cred.to_dict().get("access_token_masked") if cred else None),
                },
            }
            if include_reason:
                item["available_reason"] = reason
            result.append(item)

        return result

    def filter_available_ids(self, ad_account_ids: List[str]) -> Tuple[List[str], List[Dict]]:
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
            ok, reason = self.check_available(account)
            if ok:
                available_ids.append(pk)
            else:
                rejected.append({"account_id": account.account_id, "reason": reason})

        return available_ids, rejected
