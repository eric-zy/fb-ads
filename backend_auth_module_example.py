# 后端用户认证和账户管理模块

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from typing import List, Optional
import jwt
from passlib.context import CryptContext

from core.database import get_db
from core.logger import logger
from config.settings import settings

# 密码哈希
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 认证路由
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ==================== 数据模型 ====================

class LoginRequest(BaseModel):
    """登录请求"""
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    """用户响应"""
    id: str
    email: str
    username: str
    role: str
    company_id: str
    permissions: List[str]
    settings: dict

    class Config:
        from_attributes = True

class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str
    user: UserResponse

class UserCreateRequest(BaseModel):
    """用户创建请求"""
    email: EmailStr
    password: str
    username: str
    company_id: Optional[str] = None

# ==================== 辅助函数 ====================

def hash_password(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=7)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm="HS256"
    )
    return encoded_jwt

def verify_token(token: str) -> dict:
    """验证令牌"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"]
        )
        return payload
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的令牌"
        )

# ==================== 认证端点 ====================

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """用户登录"""
    try:
        from models import User
        
        # 查找用户
        user = db.query(User).filter(User.email == request.email).first()
        if not user or not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="邮箱或密码错误"
            )
        
        # 生成令牌
        access_token = create_access_token({
            "sub": user.id,
            "email": user.email,
            "role": user.role
        })
        
        logger.info(f"User {user.email} logged in")
        
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserResponse(
                id=user.id,
                email=user.email,
                username=user.username,
                role=user.role,
                company_id=user.company_id,
                permissions=user.permissions or [],
                settings=user.settings or {}
            )
        )
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录失败"
        )

@router.post("/logout")
async def logout():
    """用户登出"""
    logger.info("User logged out")
    return {"message": "已登出"}

@router.post("/register", response_model=UserResponse)
async def register(
    request: UserCreateRequest,
    db: Session = Depends(get_db)
):
    """用户注册"""
    try:
        from models import User
        
        # 检查邮箱是否已存在
        existing_user = db.query(User).filter(User.email == request.email).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被注册"
            )
        
        # 创建新用户
        new_user = User(
            id=f"user_{datetime.utcnow().timestamp()}",
            email=request.email,
            username=request.username,
            hashed_password=hash_password(request.password),
            company_id=request.company_id,
            role="user",
            permissions=["view_dashboard", "view_campaigns"],
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"New user registered: {request.email}")
        
        return UserResponse(
            id=new_user.id,
            email=new_user.email,
            username=new_user.username,
            role=new_user.role,
            company_id=new_user.company_id,
            permissions=new_user.permissions or [],
            settings=new_user.settings or {}
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="注册失败"
        )
