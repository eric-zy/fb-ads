# 用户模型

from sqlalchemy import Column, String, DateTime, Boolean, JSON, Index
from datetime import datetime
from core.database import Base

class User(Base):
    """用户模型"""
    __tablename__ = "users"
    
    id = Column(String(50), primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    # 公司和角色
    company_id = Column(String(50), index=True)
    role = Column(String(50), default="user")  # admin, manager, user
    
    # 权限
    permissions = Column(JSON, default=[])
    settings = Column(JSON, default={})
    
    # 状态
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)
    
    __table_args__ = (
        Index('ix_email_active', 'email', 'is_active'),
    )
    
    def __repr__(self):
        return f"<User {self.email}>"

class UserAccount(Base):
    """用户-广告账户关联"""
    __tablename__ = "user_accounts"
    
    id = Column(String(50), primary_key=True, index=True)
    user_id = Column(String(50), index=True, nullable=False)
    account_id = Column(String(50), index=True, nullable=False)
    
    # 权限
    role = Column(String(50), default="viewer")  # owner, editor, viewer
    
    # 时间戳
    assigned_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_user_account', 'user_id', 'account_id'),
    )
    
    def __repr__(self):
        return f"<UserAccount user={self.user_id} account={self.account_id}>"
