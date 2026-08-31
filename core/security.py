"""凭据加密工具

对齐设计文档：
- 第 9 节 Token / Credential 管理：Access Token 必须加密存储
- 第 41.1 节：Token 不得在前端暴露、不得写入 Git、不得写入普通日志

使用 Fernet（对称加密，基于 cryptography），密钥由 settings.SECRET_KEY 派生。
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from config.settings import settings

logger = logging.getLogger(__name__)


def _derive_key(secret: str) -> bytes:
    """由 SECRET_KEY 派生 32 字节 urlsafe base64 密钥"""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    return Fernet(_derive_key(settings.SECRET_KEY))


def encrypt_token(plain: str | None) -> str:
    """加密 Access Token，返回密文字符串"""
    if not plain:
        return ""
    try:
        return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    except Exception as e:  # 加密失败不能静默吞掉明文
        logger.error(f"[security] token 加密失败: {type(e).__name__}")
        raise


def decrypt_token(cipher: str | None) -> str:
    """解密 Access Token；失败返回空串（不向外泄露异常细节）"""
    if not cipher:
        return ""
    try:
        return _get_fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("[security] 凭据解密失败：密文不合法或 SECRET_KEY 已变更")
        return ""
    except Exception as e:
        logger.error(f"[security] 凭据解密异常: {type(e).__name__}")
        return ""


def mask_token(token: str | None) -> str:
    """日志脱敏：仅保留首尾各 4 位，避免 Token 落入普通日志"""
    if not token:
        return ""
    if len(token) <= 12:
        return "***"
    return f"{token[:4]}...{token[-4:]}"
