"""凭据模型（Meta 账号管理 V1 —— 设计文档 §4）

对应文档中的 `meta_credentials` 表。表名沿用 `credentials`。

关系方向（与文档 §5 的 `businesses.credential_id` 不同，本项目保留反向）：

    meta_accounts (BM)  ──1:N──►  credentials

即**一个 BM 可拥有多条凭据**。这样 Token 轮换时旧凭据可以保留为 DISABLED
便于回溯；若改成"BM 指向单个默认凭据"，轮换历史就会丢失。

安全约定（文档 §27）：
    - 明文 Token 永不落库，只存 Fernet 密文
    - 对外接口默认只返回脱敏值，查看明文需显式确认并写审计日志
    - 日志禁止打印完整 Token
"""
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from sqlalchemy import Index
from core.database import Base
from core.enums import CredentialSource, CredentialStatus
from core.security import decrypt_token, encrypt_token, mask_token
from core.tenant import TenantMixin


class Credential(TenantMixin, Base):
    """凭据（加密的 Meta Access Token，租户级敏感数据）"""

    __tablename__ = "credentials"

    id = Column(String(50), primary_key=True, index=True)

    # 归属 BM（文档 §4 未直接关联，本项目保留以支持一 BM 多凭据与轮换留痕）
    meta_account_id = Column(
        String(50),
        ForeignKey("meta_accounts.id"),
        nullable=True,
        index=True,
        comment="归属 BM（Business Manager）",
    )
    # 显式指定 foreign_keys：BM 侧新增 default_credential_id 后，
    # Credential 与 MetaAccount 之间存在两条外键路径，不指定会触发
    # AmbiguousForeignKeysError。
    meta_account = relationship(
        "MetaAccount", foreign_keys=[meta_account_id], backref="credentials"
    )

    # ---------- 文档 §4 字段 ----------
    name = Column(String(255), comment="凭据名称，便于运维识别")
    app_id = Column(String(128), comment="Meta App ID")

    access_token_encrypted = Column(Text, nullable=False, comment="加密后的 Access Token")
    token_type = Column(
        String(32), default="USER", comment="USER / SYSTEM_USER / PAGE"
    )
    expires_at = Column(DateTime, comment="过期时间，NULL 表示长期有效")

    status = Column(
        String(32),
        default=CredentialStatus.ACTIVE.value,
        comment="ACTIVE / VERIFYING / EXPIRED / INVALID / DISABLED",
    )
    last_error = Column(Text, comment="最近一次校验/调用失败原因")
    last_verified_at = Column(DateTime, comment="最近一次校验成功时间")

    # ---------- 溯源字段（OAuth 授权留痕） ----------
    # Token 一旦出问题，运维需要立刻回答三件事：
    #   谁授的权？授了哪些权限？用的是哪个 Meta 账号？
    # 没有这些字段就只能翻应用日志，甚至无从查起。
    source = Column(
        String(32),
        default=CredentialSource.MANUAL.value,
        comment="来源：MANUAL（手工录入）/ OAUTH（OAuth 授权）",
    )
    scopes = Column(JSON, comment="实际授予的 Meta 权限列表（OAUTH 来源时记录）")
    granted_by_user_id = Column(
        String(50), ForeignKey("users.id"), comment="发起授权的本系统用户"
    )
    meta_user_id = Column(String(64), comment="授权方的 Meta 用户 ID")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_credentials_tenant_meta", "tenant_id", "meta_account_id"),
        Index("ix_credentials_tenant_status", "tenant_id", "status"),
    )

    # ---- 明文读写一律经过加解密，业务层不接触密文 ----
    def set_access_token(self, plain_token: str) -> None:
        """写入明文 Token（内部自动加密）"""
        self.access_token_encrypted = encrypt_token(plain_token)

    def get_access_token(self) -> str:
        """读取明文 Token（内部自动解密）"""
        return decrypt_token(self.access_token_encrypted)

    def is_expired(self) -> bool:
        """是否已过期（无过期时间视为长期有效）"""
        if not self.expires_at:
            return False
        return self.expires_at < datetime.utcnow()

    def to_dict(self, include_token: bool = False) -> dict:
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "meta_account_id": self.meta_account_id,
            "name": self.name,
            "app_id": self.app_id,
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status,
            "last_error": self.last_error,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "is_expired": self.is_expired(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        # 默认绝不向前端返回明文 Token（文档 §27）
        if include_token:
            data["access_token"] = self.get_access_token()
        else:
            data["access_token_masked"] = mask_token(self.get_access_token())
        return data
