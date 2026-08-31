"""BM 主账号服务（Meta 账号管理 V1 —— 文档 §21 / §22）

分层要求（文档 §21）：Controller 不得直接操作 SDK。

    Controller(API)
        ↓
    BusinessService（本文件）
        ↓
    MetaClient
        ↓
    facebook-business-sdk
        ↓
    Meta Marketing API

职责：
    - 校验 Credential / BM 与 Meta 的连通性（文档 §14 添加 BM 时的"验证连接"）
    - 拉取 BM 基础信息并回填（timezone / currency）
"""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from config.settings import settings
from core.enums import ErrorCategory
from core.logger import logger
from models import MetaAccount
from services.meta.client import MetaClient
from services.meta.errors import MetaApiError


def _credential_service(db):
    """延迟导入，避免与 services.credential_service 形成循环导入"""
    from services.credential_service import CredentialService

    return CredentialService(db)


class BusinessService:
    """BM 主账号相关业务"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _resolve_token(self, business: MetaAccount) -> str:
        """解析 BM 可用的明文 Token；凭据不可用时转为 AUTH 类 MetaApiError"""
        from services.credential_service import CredentialError

        try:
            token, _ = _credential_service(self.db).resolve_token_for_meta(business.id)
            return token
        except CredentialError as e:
            raise MetaApiError(str(e), category=ErrorCategory.AUTH)

    def _dev_mode_result(self, business: MetaAccount, action: str) -> Dict:
        """未配置真实 FB 凭据时的降级结果（与 fb_client 的降级策略保持一致）"""
        logger.warning(
            f"[DEV] 未配置 FB 凭据，跳过 BM {business.business_id} 的{action}（开发模式）"
        )
        return {"ok": True, "dev_mode": True, "error": None, "business": None}

    # ------------------------------------------------------------------
    # 连通性校验
    # ------------------------------------------------------------------
    def verify_connection(self, business: MetaAccount) -> Dict:
        """验证该 BM 与其凭据能否连通 Meta

        返回:
            {
                "ok": bool,
                "dev_mode": bool,     # 未配置真实 FB 凭据时的降级
                "error": str | None,
                "business": {...} | None,   # Meta 返回的 BM 信息
                "business_id_matched": bool # Meta 返回的 ID 与本地是否一致
            }
        """
        if not settings.FB_ACCESS_TOKEN:
            return self._dev_mode_result(business, "连通性校验")

        try:
            token = self._resolve_token(business)
            client = MetaClient(access_token=token)
            data = client.get_business(business.business_id)
        except MetaApiError as e:
            logger.error(f"[BusinessService] 校验 BM {business.business_id} 失败: {e}")
            return {"ok": False, "dev_mode": False, "error": str(e), "business": None,
                    "business_id_matched": False}

        meta_business_id = str(data.get("id", "")).strip()
        matched = meta_business_id == str(business.business_id).strip()

        return {
            "ok": matched,
            "dev_mode": False,
            "error": None if matched else
                     f"Meta 返回的 Business ID({meta_business_id}) 与本地({business.business_id}) 不一致",
            "business": data,
            "business_id_matched": matched,
        }

    # ------------------------------------------------------------------
    # 基础信息回填
    # ------------------------------------------------------------------
    def fetch_business_info(self, business: MetaAccount) -> Optional[Dict]:
        """拉取并回填 BM 的 timezone / currency / 名称

        返回 Meta 原始数据；dev 模式或失败时返回 None（不影响调用方主流程）。
        """
        if not settings.FB_ACCESS_TOKEN:
            self._dev_mode_result(business, "信息拉取")
            return None

        try:
            token = self._resolve_token(business)
            data = MetaClient(access_token=token).get_business(business.business_id)
        except MetaApiError as e:
            logger.error(f"[BusinessService] 拉取 BM {business.business_id} 信息失败: {e}")
            return None

        if data.get("name"):
            business.name = data["name"]
        if data.get("currency"):
            business.currency = data["currency"]
        if data.get("timezone_id"):
            business.timezone = str(data["timezone_id"])

        return data
