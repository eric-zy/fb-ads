"""Connector 凭据仓储接口。

T06 先定义边界，后续由海外数据库实现。任何调用方都不应从该接口取回明文 Token。
"""

from typing import Any, Protocol


class CredentialVault(Protocol):
    def save_oauth_result(self, *, access_token: str, meta_user_id: str | None, expires_at: Any, scopes: list[str]) -> str:
        """加密保存 Token，仅返回 opaque credential_id。"""
        ...


from fb_connector.credential_store import DatabaseCredentialVault
