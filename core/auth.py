"""认证模块 - JWT和密码管理"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from typing import Optional, Dict
import jwt
import hashlib

from config.settings import settings
from core.logger import logger
from core.database import get_db

# HTTP Bearer认证
security = HTTPBearer()


class AuthManager:
    """认证管理器（密码统一使用 sha256，与登录逻辑一致）"""

    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码（sha256）"""
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码（sha256 比对）"""
        return AuthManager.hash_password(plain_password) == hashed_password

    @staticmethod
    def create_access_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
        """创建访问令牌

        Args:
            data: 令牌包含的数据
            expires_delta: 过期时间差

        Returns:
            JWT令牌
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(hours=24)

        to_encode.update({"exp": expire, "iat": datetime.utcnow()})

        encoded_jwt = jwt.encode(
            to_encode,
            settings.SECRET_KEY,
            algorithm="HS256"
        )
        return encoded_jwt

    @staticmethod
    def verify_token(token: str) -> Dict:
        """验证令牌

        Args:
            token: JWT令牌

        Returns:
            令牌载荷

        Raises:
            HTTPException: 令牌无效
        """
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=["HS256"]
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="令牌已过期"
            )
        except jwt.JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的令牌"
            )


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """获取当前用户

    Args:
        credentials: HTTP认证凭证

    Returns:
        用户信息

    Raises:
        HTTPException: 认证失败
    """
    token = credentials.credentials
    payload = AuthManager.verify_token(token)

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌"
        )

    return {"user_id": user_id, "email": payload.get("email")}


async def get_current_active_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: "Session" = Depends(get_db),
) -> "User":
    """解析 JWT 并返回数据库中的 User ORM 对象（供管理接口使用）

    与 main.py 的登录逻辑一致：令牌由 backend 签发，此处仅做签名校验 + 查库。
    """
    from models import User

    payload = AuthManager.verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已注销",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )
    return user


async def require_admin(
    current_user: "User" = Depends(get_current_active_user),
) -> "User":
    """要求管理员角色"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
