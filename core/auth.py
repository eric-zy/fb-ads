"""认证模块 - JWT和密码管理

多租户改造：
    - JWT 增加 `tid`（tenant_id）与 `role` claim，
      `core.database.get_db` 会据此建立租户上下文（隔离兜底）
    - `get_current_active_user` 在返回 User 前把租户 ID 写入上下文
    - 角色升级为 `UserRole`（platform_admin / tenant_admin / manager / user）
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from typing import Optional, Dict
import jwt
import hashlib

from config.settings import settings
from core.logger import logger
from core.database import get_db
from core.tenant import set_current_tenant_id

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

        # 多租户：把 tenant_id 同步写入 `tid` claim（短名，减小 token 体积）。
        # core.database.get_db 会从 token 中读 tid 建立租户上下文。
        if to_encode.get("tenant_id") and not to_encode.get("tid"):
            to_encode["tid"] = to_encode["tenant_id"]

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

    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "tenant_id": payload.get("tid"),
        "role": payload.get("role"),
    }


async def get_current_active_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: "Session" = Depends(get_db),
) -> "User":
    """解析 JWT 并返回数据库中的 User ORM 对象（供管理接口使用）

    与 main.py 的登录逻辑一致：令牌由 backend 签发，此处仅做签名校验 + 查库。

    副产物：**把用户所属租户写入上下文**，使后续 ORM 查询自动带上
    `tenant_id` 过滤。平台管理员（`tenant_id` 为空）不写入上下文，
    其查询需要显式 `bypass_tenant()`。
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

    # 建立租户上下文：优先用库里的实时值（避免令牌中的 tid 过期）
    tenant_id = getattr(user, "tenant_id", None)
    set_current_tenant_id(tenant_id)
    return user


async def get_current_tenant(
    current_user: "User" = Depends(get_current_active_user),
    db: "Session" = Depends(get_db),
) -> "Tenant":
    """获取当前用户所属租户（并校验租户可用状态）"""
    from models import Tenant

    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="平台账号不属于任何租户，请显式指定 tenant_id 后操作",
        )
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="租户不存在")
    if not tenant.is_active():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="租户已停用或订阅已过期，请联系平台",
        )
    return tenant


async def require_admin(
    current_user: "User" = Depends(get_current_active_user),
) -> "User":
    """要求管理员角色（平台管理员或租户管理员）"""
    from models.tenant import UserRole

    if not UserRole.is_admin(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


async def require_platform_admin(
    current_user: "User" = Depends(get_current_active_user),
) -> "User":
    """要求平台管理员（可跨租户，使用场景配合 bypass_tenant）"""
    from models.tenant import UserRole

    if not UserRole.is_platform_admin(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要平台管理员权限",
        )
    return current_user
