import base64
import hashlib
import uuid
from cryptography.fernet import Fernet
from config.settings import settings
from fb_connector.models import ConnectorCredential, connector_session_factory

def _cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)

class DatabaseCredentialVault:
    """海外凭据仓储；对外仅返回 credential_id，不返回明文 Token。"""
    def save_oauth_result(self, *, access_token: str, meta_user_id, expires_at, scopes: list[str]) -> str:
        credential_id = uuid.uuid4().hex
        session = connector_session_factory()
        try:
            session.add(ConnectorCredential(id=credential_id, app_id=settings.FB_APP_ID,
                access_token_encrypted=_cipher().encrypt(access_token.encode()).decode(),
                token_type="USER", meta_user_id=meta_user_id, scopes=scopes, expires_at=expires_at))
            session.commit()
            return credential_id
        finally:
            session.close()

    def get_access_token(self, credential_id: str) -> str:
        session = connector_session_factory()
        try:
            row = session.get(ConnectorCredential, credential_id)
            if not row or row.status != "ACTIVE":
                raise KeyError("凭据不存在或已失效")
            return _cipher().decrypt(row.access_token_encrypted.encode()).decode()
        finally:
            session.close()
