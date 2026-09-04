"""凭据解析服务（设计文档第 9 节）

统一入口：给定一个广告账户或 BM，解析出可用的明文 Access Token。

解析优先级：
    1. credentials 表（加密存储，推荐）
    2. meta_accounts.access_token（兼容改造前的历史明文数据）
    3. 全局 settings.FB_ACCESS_TOKEN（最后兜底）

这是"多 BM / 多广告账户"架构的关键：每个账户解析出自己的 token，
再用它构造独立的 MetaClient，而不是全系统共用一个全局 token。
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config.settings import settings
from core.enums import CredentialSource, CredentialStatus
from core.logger import logger
from core.security import mask_token
from models import AdAccount, Credential, MetaAccount
from services.meta import MetaAdsService, MetaClient
from services.meta.errors import MetaApiError


class CredentialError(Exception):
    """凭据不可用（缺失 / 解密失败）"""


class CredentialExpiredError(CredentialError):
    """凭据已过期

    与 CredentialError 的关键区别：**绝不允许回退到全局 Token**。
    多 BM 场景下，某 BM 凭据失效后若回退到全局或其它 BM 的 Token，
    会变成"用 A 的身份操作 B 的账户"的串号事故，因此必须直接失败。
    """


class CredentialService:
    """凭据解析与状态标记"""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def resolve_token(self, ad_account_id: str) -> Tuple[str, Optional[Credential]]:
        """解析广告账户可用的明文 token，返回 (token, credential|None)"""
        account = self.db.query(AdAccount).filter(AdAccount.id == ad_account_id).first()
        if not account:
            raise CredentialError(f"广告账户不存在: {ad_account_id}")

        # 1) 优先使用加密凭据表（2 / 3 级回退在 resolve_token_for_meta 内完成）
        # 注意：AdAccount 通过 `business_id` 关联所属 BM，
        # 不存在 `meta_account_id` 属性（那是 Credential 上的字段）。
        if account.business_id:
            try:
                return self.resolve_token_for_meta(account.business_id)
            except CredentialExpiredError:
                # 过期必须直接失败，不能回退到全局 Token（避免多 BM 串号）
                raise
            except CredentialError as e:
                logger.warning(
                    f"[CredentialService] 账户 {ad_account_id} 凭据解析失败: {e}"
                )

        # 4) 最后兜底：全局配置
        if settings.FB_ACCESS_TOKEN:
            logger.warning("[CredentialService] 回退使用全局 FB_ACCESS_TOKEN")
            return settings.FB_ACCESS_TOKEN, None

        raise CredentialError(f"广告账户 {ad_account_id} 无可用凭据")

    def get_meta_credential(self, meta_account_id: str) -> Optional[Credential]:
        """取该 BM 当前生效（ACTIVE）的凭据，没有则返回 None

        解析顺序：
            1. BM 显式指定的 `default_credential_id`（管理员可人工选择）
            2. 该 BM 下最新一条 ACTIVE 凭据（向后兼容的推导逻辑）

        指定的默认凭据若已被禁用/过期，会记录 warning 并回退到推导逻辑，
        避免因指向失效凭据导致整个 BM 不可用。
        """
        meta = (
            self.db.query(MetaAccount)
            .filter(MetaAccount.id == meta_account_id)
            .first()
        )
        if meta and meta.default_credential_id:
            cred = (
                self.db.query(Credential)
                .filter(
                    Credential.id == meta.default_credential_id,
                    Credential.status == CredentialStatus.ACTIVE.value,
                )
                .first()
            )
            if cred:
                return cred
            logger.warning(
                f"[CredentialService] BM {meta_account_id} 指定的默认凭据 "
                f"{meta.default_credential_id} 不可用，回退为最新 ACTIVE 凭据"
            )

        return (
            self.db.query(Credential)
            .filter(
                Credential.meta_account_id == meta_account_id,
                Credential.status == CredentialStatus.ACTIVE.value,
            )
            .order_by(Credential.created_at.desc())
            .first()
        )

    def resolve_token_for_meta(self, meta_account_id: str) -> Tuple[str, Optional[Credential]]:
        """解析某个 BM 可用的明文 token

        优先级：
            1. credentials 表（加密存储，唯一正式来源）
            2. 全局 settings.FB_ACCESS_TOKEN（最后兜底）

        Meta 账号管理 V1 之后 `meta_accounts.access_token` 列已移除
        （BM 主表不再存明文 Token），因此不再有"回退 BM 明文"这一级。

        返回 (token, credential|None)；credential 为 None 表示走的是全局兜底。
        """
        if not meta_account_id:
            raise CredentialError("未指定 BM 主账号，无法解析凭据")

        # 1) 加密凭据表
        cred = self.get_meta_credential(meta_account_id)
        if cred:
            if cred.is_expired():
                cred.status = CredentialStatus.EXPIRED.value
                self.db.commit()
                raise CredentialExpiredError(
                    f"BM {meta_account_id} 的凭据已过期，请更新 Token"
                )
            token = cred.get_access_token()
            if token:
                logger.debug(
                    f"[CredentialService] BM {meta_account_id} 使用凭据 {cred.id} "
                    f"({mask_token(token)})"
                )
                return token, cred
            logger.error(f"[CredentialService] 凭据 {cred.id} 解密失败")

        # 2) 全局兜底
        if settings.FB_ACCESS_TOKEN:
            logger.warning("[CredentialService] 回退使用全局 FB_ACCESS_TOKEN")
            return settings.FB_ACCESS_TOKEN, None

        raise CredentialError(f"BM {meta_account_id} 无可用凭据")

    def build_service(self, ad_account_id: str, **service_kwargs) -> MetaAdsService:
        """构建该账户可用的 MetaAdsService（多账户架构的入口）"""
        token, _ = self.resolve_token(ad_account_id)
        client = MetaClient(access_token=token)
        return MetaAdsService(client, **service_kwargs)

    # ------------------------------------------------------------------
    # 状态标记（设计文档第 9 节：支持过期检测与权限异常标记）
    # ------------------------------------------------------------------
    def mark_invalid(self, credential: Optional[Credential], reason: str) -> None:
        """将凭据标记为 INVALID"""
        if not credential:
            return
        credential.status = CredentialStatus.INVALID.value
        credential.last_error = reason
        self.db.commit()
        logger.warning(f"[CredentialService] 凭据 {credential.id} 标记为 INVALID: {reason}")

    def mark_invalid_by_account(self, ad_account_id: str, reason: str) -> None:
        """按广告账户定位其 BM 的当前凭据并标记异常"""
        account = self.db.query(AdAccount).filter(AdAccount.id == ad_account_id).first()
        if not account or not account.business_id:
            return
        cred = (
            self.db.query(Credential)
            .filter(
                Credential.meta_account_id == account.business_id,
                Credential.status == CredentialStatus.ACTIVE.value,
            )
            .first()
        )
        self.mark_invalid(cred, reason)

    # ------------------------------------------------------------------
    # 写入 / 轮换（设计文档第 9 节：Token 更换不影响 BM / 账户主数据）
    # ------------------------------------------------------------------
    def create_for_meta(
        self,
        meta_account_id: str,
        plain_token: str,
        token_type: str = "USER",
        expires_at: Optional[datetime] = None,
        replace_active: bool = True,
        source: str = None,
        scopes: Optional[List[str]] = None,
        granted_by_user_id: Optional[str] = None,
        meta_user_id: Optional[str] = None,
    ) -> Credential:
        """为指定 BM 写入加密凭据

        Args:
            meta_account_id: 归属 BM
            plain_token: 明文 Token（内部加密后落库，明文不落盘）
            token_type: USER / SYSTEM_USER / PAGE
            expires_at: 过期时间，None 表示长期有效
            replace_active: True=把该 BM 现有 ACTIVE 凭据置为 DISABLED 后新建（轮换）；
                            False=直接追加一条（可能并存多条 ACTIVE）
            source: 来源 MANUAL / OAUTH，默认 MANUAL
            scopes: 实际授予的权限列表（OAuth 场景）
            granted_by_user_id: 发起授权的本系统用户
            meta_user_id: 授权方的 Meta 用户 ID
        """
        if not plain_token:
            raise CredentialError("Token 不能为空")

        if replace_active:
            for old in (
                self.db.query(Credential)
                .filter(
                    Credential.meta_account_id == meta_account_id,
                    Credential.status == CredentialStatus.ACTIVE.value,
                )
                .all()
            ):
                old.status = CredentialStatus.DISABLED.value

        cred = Credential(
            id=uuid.uuid4().hex,
            meta_account_id=meta_account_id,
            token_type=token_type or "USER",
            expires_at=expires_at,
            status=CredentialStatus.ACTIVE.value,
            source=source or CredentialSource.MANUAL.value,
            scopes=list(scopes) if scopes else None,
            granted_by_user_id=granted_by_user_id,
            meta_user_id=meta_user_id,
        )
        cred.set_access_token(plain_token)
        self.db.add(cred)
        self.db.commit()
        self.db.refresh(cred)

        logger.info(
            f"[CredentialService] BM {meta_account_id} 写入凭据 {cred.id} "
            f"({mask_token(plain_token)})"
        )
        return cred

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------
    @staticmethod
    def verify_token(plain_token: str) -> Dict[str, Any]:
        """校验 Token 是否有效（调 Meta Graph API 的 /me）

        返回:
            {
                "valid": bool,        # Token 是否可用
                "dev_mode": bool,     # 是否开发降级模式（未配置真实 FB 凭据）
                "error": str | None,  # 失败原因
                "token_info": {...},  # 命中时返回的 Token 归属信息
            }
        """
        if not plain_token:
            return {"valid": False, "dev_mode": False, "error": "Token 为空", "token_info": None}

        # 与 services/fb_client.py 保持一致的开发降级策略：
        # 未配置真实 FB 凭据时不做真实网络调用，避免本地开发被外部依赖卡死
        if not settings.FB_ACCESS_TOKEN:
            logger.warning("[CredentialService] 未配置 FB 凭据，跳过 Token 真实校验（开发模式）")
            return {"valid": True, "dev_mode": True, "error": None, "token_info": None}

        try:
            client = MetaClient(access_token=plain_token)
            response = client.api.call("GET", "me", params={"fields": "id,name"})
            data = response.json()
        except MetaApiError as e:
            return {"valid": False, "dev_mode": False, "error": str(e)[:300], "token_info": None}
        except Exception as e:  # SDK / 网络异常
            return {
                "valid": False,
                "dev_mode": False,
                "error": f"{type(e).__name__}: {str(e)[:300]}",
                "token_info": None,
            }

        if not data or not data.get("id"):
            return {
                "valid": False,
                "dev_mode": False,
                "error": "接口未返回有效身份信息",
                "token_info": None,
            }

        return {
            "valid": True,
            "dev_mode": False,
            "error": None,
            "token_info": {"id": data.get("id"), "name": data.get("name")},
        }

    def verify_credential(self, credential: Credential) -> Dict[str, Any]:
        """校验一条凭据并回写状态（last_verified_at / INVALID + last_error）"""
        token = credential.get_access_token()
        result = self.verify_token(token)

        if result["valid"]:
            credential.last_verified_at = datetime.utcnow()
            credential.last_error = None
            # 校验通过说明 Token 可用，若此前被标记为 EXPIRED/INVALID 则恢复
            if credential.status in (
                CredentialStatus.EXPIRED.value,
                CredentialStatus.INVALID.value,
            ) and not credential.is_expired():
                credential.status = CredentialStatus.ACTIVE.value
        else:
            credential.status = CredentialStatus.INVALID.value
            credential.last_error = result.get("error")

        self.db.commit()
        self.db.refresh(credential)
        return result
