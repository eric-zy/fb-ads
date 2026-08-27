"""认证模块 - JWT和密码管理"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from datetime import datetime, timedelta
from typing import Optional, Dict
import jwt
from passlib.context import CryptContext

from config.settings import settings
from core.logger import logger

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer认证
security = HTTPBearer()

class AuthManager:
    """认证管理器"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码"""
        return pwd_context.hash(password)
    
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)
    
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

async def get_current_user(credentials: HTTPAuthCredentials = Depends(security)) -> Dict:
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
