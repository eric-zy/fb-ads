from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from core.database import Base
from core.tenant import TenantMixin
from core.security import encrypt_token, decrypt_token, mask_token

class SinanCredential(TenantMixin, Base):
    __tablename__ = 'sinan_credentials'
    id = Column(String(50), primary_key=True, index=True)
    base_url = Column(String(255), nullable=False, default='https://api.sinan-partner.com')
    app_id = Column(String(64), nullable=False)
    account_encrypted = Column(Text, nullable=False)
    password_encrypted = Column(Text, nullable=False)
    menu_id = Column(String(128), nullable=False)
    access_token_encrypted = Column(Text, default='')
    refresh_token_encrypted = Column(Text, default='')
    status = Column(String(32), default='PENDING')
    last_error = Column(Text)
    last_verified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    def set_account(self, v): self.account_encrypted = encrypt_token(v)
    def set_password(self, v): self.password_encrypted = encrypt_token(v)
    def get_account(self): return decrypt_token(self.account_encrypted)
    def get_password(self): return decrypt_token(self.password_encrypted)
    def set_tokens(self, access, refresh):
        self.access_token_encrypted = encrypt_token(access); self.refresh_token_encrypted = encrypt_token(refresh)
    def get_access_token(self): return decrypt_token(self.access_token_encrypted)
    def get_refresh_token(self): return decrypt_token(self.refresh_token_encrypted)
    def to_dict(self):
        return {'id': self.id, 'base_url': self.base_url, 'app_id': self.app_id, 'account_masked': mask_token(self.get_account()), 'menu_id': self.menu_id, 'status': self.status, 'configured': True, 'verified': self.status == 'ACTIVE', 'last_verified_at': self.last_verified_at.isoformat() if self.last_verified_at else None, 'last_error': self.last_error}
