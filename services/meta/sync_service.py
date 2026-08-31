"""Meta 同步服务（Meta 账号管理 V1 —— 文档 §23 / §24 / §25）

流程（文档 §23）：

    Business → Credential → Meta API → Normalize → Validate → Upsert → Update Sync Status

Upsert 规则（文档 §24）：
    - 唯一键：(business_id, account_id)，同一 BM 内不重复；跨 BM 允许同一 act_xxx
    - 已存在则 UPDATE，不存在则 INSERT
    - **禁止同步覆盖 system_status**：管理员禁用过的账户，即使 Meta 侧正常也不自动恢复

同步原则（文档 §3）：
    Meta 不再返回的账户**不要直接删除**，只记录，避免误删历史数据。

日志（文档 §10）：
    每次同步写 meta_sync_logs，与 audit_logs（操作审计）分开。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from config.settings import settings
from core.logger import logger
from models import (
    AdAccount,
    MetaAccount,
    MetaSyncLog,
    # SyncStatus 是 BM 上的同步状态位（models/meta_account.py），
    # SyncLogStatus 是同步日志的状态（models/sync_log.py），两者别混淆
    SyncStatus,
    SyncLogStatus,
    SyncType,
    SystemStatus,
)
from services.meta.business_service import BusinessService
from services.meta.client import MetaClient
from services.meta.errors import MetaApiError


def _minor_int(value) -> Optional[int]:
    """Meta 金额字段返回最小货币单位字符串（"10000" = $100.00）"""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class MetaSyncService:
    """Meta 数据同步"""

    def __init__(self, db: Session):
        self.db = db
        self.business_service = BusinessService(db)

    # ------------------------------------------------------------------
    # 同步日志
    # ------------------------------------------------------------------
    def _start_log(
        self, business_id: Optional[str], sync_type: str, celery_task_id: Optional[str] = None
    ) -> MetaSyncLog:
        log = MetaSyncLog(
            id=__import__("uuid").uuid4().hex,
            business_id=business_id,
            sync_type=sync_type,
            status=SyncLogStatus.RUNNING.value,
            celery_task_id=celery_task_id,
            started_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        self.db.add(log)
        self.db.flush()
        return log

    def _finish_log(
        self,
        log: MetaSyncLog,
        *,
        total: int,
        success: int,
        failed: int,
        error_message: Optional[str] = None,
        error_detail: Optional[List[Dict]] = None,
    ) -> MetaSyncLog:
        import json

        log.total_count = total
        log.success_count = success
        log.failed_count = failed
        log.error_message = error_message
        log.error_detail = json.dumps(error_detail, ensure_ascii=False) if error_detail else None
        log.finished_at = datetime.utcnow()

        if failed == 0:
            log.status = SyncLogStatus.SUCCESS.value
        elif success == 0:
            log.status = SyncLogStatus.FAILED.value
        else:
            log.status = SyncLogStatus.PARTIAL_SUCCESS.value

        self.db.commit()
        self.db.refresh(log)
        return log

    def _dev_mode_log(self, business_id: Optional[str], sync_type: str) -> MetaSyncLog:
        """未配置真实 FB 凭据时的降级日志"""
        logger.warning(f"[DEV] 未配置 FB 凭据，跳过 {sync_type} 同步")
        log = self._start_log(business_id, sync_type)
        return self._finish_log(
            log, total=0, success=0, failed=0,
            error_message="开发模式：未配置 FB_ACCESS_TOKEN，未连接 Meta",
        )

    # ------------------------------------------------------------------
    # 同步 BM 基础信息
    # ------------------------------------------------------------------
    def sync_business(self, business_id: str) -> MetaSyncLog:
        """同步单个 BM 的基础信息（timezone / currency / 名称）"""
        if not settings.FB_ACCESS_TOKEN:
            return self._dev_mode_log(business_id, SyncType.BUSINESS.value)

        business = self.db.query(MetaAccount).filter(MetaAccount.id == business_id).first()
        if not business:
            raise ValueError(f"BM 不存在: {business_id}")

        log = self._start_log(business_id, SyncType.BUSINESS.value)
        business.sync_status = SyncStatus.SYNCING.value
        self.db.commit()

        try:
            data = self.business_service.fetch_business_info(business)
        except MetaApiError as e:
            business.sync_status = SyncStatus.FAILED.value
            business.last_sync_error = str(e)
            self.db.commit()
            return self._finish_log(log, total=1, success=0, failed=1, error_message=str(e))

        business.sync_status = SyncStatus.SUCCESS.value
        business.last_synced_at = datetime.utcnow()
        business.last_sync_error = None
        self.db.commit()

        return self._finish_log(log, total=1, success=1, failed=0)

    # ------------------------------------------------------------------
    # 同步 BM 下的广告账户
    # ------------------------------------------------------------------
    def sync_ad_accounts(self, business_id: str) -> MetaSyncLog:
        """拉取该 BM 下的广告账户并 Upsert 入库

        注意：**不覆盖 system_status**，管理员的禁用决定必须保留。
        """
        if not settings.FB_ACCESS_TOKEN:
            return self._dev_mode_log(business_id, SyncType.AD_ACCOUNT.value)

        business = self.db.query(MetaAccount).filter(MetaAccount.id == business_id).first()
        if not business:
            raise ValueError(f"BM 不存在: {business_id}")

        log = self._start_log(business_id, SyncType.AD_ACCOUNT.value)
        business.sync_status = SyncStatus.SYNCING.value
        self.db.commit()

        try:
            token = self.business_service._resolve_token(business)
            raw_accounts: List[Dict[str, Any]] = MetaClient(
                access_token=token
            ).get_ad_accounts(business.business_id)
        except MetaApiError as e:
            business.sync_status = SyncStatus.FAILED.value
            business.last_sync_error = str(e)
            self.db.commit()
            return self._finish_log(log, total=0, success=0, failed=1, error_message=str(e))

        success, failed = 0, 0
        errors: List[Dict] = []

        for raw in raw_accounts:
            try:
                self._upsert_ad_account(business, raw)
                success += 1
            except Exception as e:  # 单条失败不影响其余（文档 §29）
                failed += 1
                errors.append({"account_id": raw.get("id"), "error": str(e)})
                logger.error(f"[MetaSync] Upsert 账户失败 {raw.get('id')}: {e}")

        business.last_synced_at = datetime.utcnow()
        business.sync_status = (
            SyncStatus.SUCCESS.value if failed == 0 else SyncStatus.FAILED.value
        )
        business.last_sync_error = errors[0]["error"] if errors else None

        return self._finish_log(
            log,
            total=len(raw_accounts),
            success=success,
            failed=failed,
            error_message=(errors[0]["error"] if errors else None),
            error_detail=errors,
        )

    def fetch_ad_accounts_from_meta(self, business_id: str) -> List[Dict[str, Any]]:
        """只拉取 Meta 侧的账户列表，**不入库**（文档 §17 导入流程第 2 步）

        供前端展示"Meta 有哪些账户"并勾选。
        """
        if not settings.FB_ACCESS_TOKEN:
            logger.warning(f"[DEV] 未配置 FB 凭据，跳过拉取 BM {business_id} 的账户")
            return []

        business = self.db.query(MetaAccount).filter(MetaAccount.id == business_id).first()
        if not business:
            raise ValueError(f"BM 不存在: {business_id}")

        token = self.business_service._resolve_token(business)
        return MetaClient(access_token=token).get_ad_accounts(business.business_id)

    def import_ad_accounts(
        self, business_id: str, account_ids: List[str]
    ) -> MetaSyncLog:
        """按勾选结果批量导入账户（文档 §17 导入流程最后一步）

        只导入给定的 account_ids，不做全量同步。
        """
        if not settings.FB_ACCESS_TOKEN:
            return self._dev_mode_log(business_id, SyncType.AD_ACCOUNT.value)

        business = self.db.query(MetaAccount).filter(MetaAccount.id == business_id).first()
        if not business:
            raise ValueError(f"BM 不存在: {business_id}")

        log = self._start_log(business_id, SyncType.AD_ACCOUNT.value)

        # 归一化：允许 act_xxx 或纯数字
        wanted = {
            aid if aid.startswith("act_") else f"act_{aid}" for aid in account_ids
        }

        try:
            token = self.business_service._resolve_token(business)
            raw_accounts = MetaClient(access_token=token).get_ad_accounts(business.business_id)
        except MetaApiError as e:
            return self._finish_log(log, total=len(wanted), success=0, failed=len(wanted),
                                    error_message=str(e))

        success, failed = 0, 0
        errors: List[Dict] = []

        for raw in raw_accounts:
            raw_id = str(raw.get("id", "")).strip()
            if not raw_id.startswith("act_"):
                raw_id = f"act_{raw_id}"
            if raw_id not in wanted:
                continue
            try:
                self._upsert_ad_account(business, raw)
                success += 1
            except Exception as e:
                failed += 1
                errors.append({"account_id": raw_id, "error": str(e)})

        # Meta 侧未返回、但用户勾选了的账户记为失败
        missing = wanted - {str(r.get("id", "")) if str(r.get("id", "")).startswith("act_")
                            else f"act_{r.get('id', '')}" for r in raw_accounts}
        for acc_id in missing:
            failed += 1
            errors.append({"account_id": acc_id, "error": "Meta 未返回该账户"})

        business.last_synced_at = datetime.utcnow()
        business.sync_status = (
            SyncStatus.SUCCESS.value if failed == 0 else SyncStatus.FAILED.value
        )
        business.last_sync_error = errors[0]["error"] if errors else None

        return self._finish_log(
            log,
            total=len(wanted),
            success=success,
            failed=failed,
            error_message=(errors[0]["error"] if errors else None),
            error_detail=errors,
        )

    def _upsert_ad_account(self, business: MetaAccount, raw: Dict[str, Any]) -> AdAccount:
        """Upsert 单个广告账户（文档 §24）

        唯一键 (business_id, account_id)；**system_status 不在覆盖范围内**。
        """
        account_id = str(raw.get("id", "")).strip()
        if not account_id:
            raise ValueError("Meta 返回数据缺少账户 ID")
        # Graph API 返回 act_xxx 形式，统一带前缀存储
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"

        account = (
            self.db.query(AdAccount)
            .filter(
                AdAccount.business_id == business.id,
                AdAccount.account_id == account_id,
            )
            .first()
        )

        if account is None:
            account = AdAccount(
                id=__import__("uuid").uuid4().hex,
                business_id=business.id,
                account_id=account_id,
                system_status=SystemStatus.ACTIVE.value,
                capabilities={},
                daily_spend_limit=0,
                monthly_spend_limit=0,
            )
            self.db.add(account)

        # ---- Meta 侧字段：每次同步覆盖 ----
        account.account_name = raw.get("name") or account.account_name
        account.account_status = (
            str(raw.get("account_status")) if raw.get("account_status") is not None else None
        )
        account.effective_status = raw.get("effective_status")
        account.currency = raw.get("currency") or account.currency
        account.timezone = raw.get("timezone_name") or account.timezone
        account.disable_reason = raw.get("disable_reason")

        spend_cap = _minor_int(raw.get("spend_cap"))
        if spend_cap is not None:
            account.spend_cap = spend_cap
        amount_spent = _minor_int(raw.get("amount_spent"))
        if amount_spent is not None:
            account.amount_spent = amount_spent
        balance = _minor_int(raw.get("balance"))
        if balance is not None:
            account.balance = balance

        account.last_synced_at = datetime.utcnow()
        account.last_sync_error = None

        # system_status / daily_spend_limit 等系统侧字段**刻意不在此修改**
        return account

    # ------------------------------------------------------------------
    # 同步单个账户
    # ------------------------------------------------------------------
    def sync_ad_account(self, ad_account_id: str) -> MetaSyncLog:
        """同步单个广告账户的 Meta 侧信息"""
        if not settings.FB_ACCESS_TOKEN:
            return self._dev_mode_log(None, SyncType.AD_ACCOUNT.value)

        account = self.db.query(AdAccount).filter(AdAccount.id == ad_account_id).first()
        if not account:
            raise ValueError(f"广告账户不存在: {ad_account_id}")

        business = account.business
        if not business:
            raise ValueError("账户未归属 BM，无法同步")

        log = self._start_log(business.id, SyncType.AD_ACCOUNT.value)

        try:
            token = self.business_service._resolve_token(business)
            raw = MetaClient(access_token=token).get_ad_account(account.account_id)
            self._upsert_ad_account(business, raw)
            self.db.commit()
        except MetaApiError as e:
            account.last_sync_error = str(e)
            self.db.commit()
            return self._finish_log(log, total=1, success=0, failed=1, error_message=str(e))

        return self._finish_log(log, total=1, success=1, failed=0)
