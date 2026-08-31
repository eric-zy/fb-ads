# ==================== 用户管理API端点 ====================

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, EmailStr
from typing import Any, Dict, List, Optional
import hashlib
import uuid

from core.database import get_db
from core.logger import logger
from core.auth import get_current_active_user, require_admin
from models import User, AdAccount
from api.accounts import account_to_dict

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _hash_password(password: str) -> str:
    """与 main.py 登录比对逻辑一致的 sha256 哈希"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

# ==================== 数据模型 ====================

class UserSettingsUpdate(BaseModel):
    """用户设置更新"""
    settings: dict

class UserAccountsResponse(BaseModel):
    """用户账户列表响应

    账户字段不再在此处单独定义：历史上 AccountResponse 只有 8 个字段，
    与 /api/v1/accounts 返回的完整字段不一致，导致前端类型与实际响应对不上。
    现在统一复用 api/accounts.py 的 account_to_dict()。
    """
    accounts: List[Dict[str, Any]]

# ==================== API端点 ====================

@router.get("/{user_id}/accounts", response_model=UserAccountsResponse)
async def get_user_accounts(
    user_id: str,
    db: Session = Depends(get_db)
):
    """获取用户的广告账户列表"""
    try:
        from models import UserAccount
        
        # 获取用户的所有账户
        user_accounts = db.query(UserAccount).filter(
            UserAccount.user_id == user_id
        ).all()
        
        account_ids = [ua.account_id for ua in user_accounts]
        
        # 查询账户详情
        accounts = db.query(AdAccount).filter(
            AdAccount.id.in_(account_ids)
        ).all()
        
        return UserAccountsResponse(
            accounts=[account_to_dict(a) for a in accounts]
        )
    except Exception as e:
        logger.error(f"Failed to get user accounts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取账户列表失败"
        )

@router.put("/{user_id}/settings")
async def update_user_settings(
    user_id: str,
    request: UserSettingsUpdate,
    db: Session = Depends(get_db)
):
    """更新用户设置"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        user.settings = request.settings
        db.commit()
        db.refresh(user)
        
        logger.info(f"User {user_id} settings updated")
        
        return {
            "message": "设置已更新",
            "settings": user.settings
        }
    except Exception as e:
        logger.error(f"Failed to update user settings: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新设置失败"
        )

@router.get("/{user_id}")
async def get_user(
    user_id: str,
    db: Session = Depends(get_db)
):
    """获取用户信息"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )
        
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "role": user.role,
            "company_id": user.company_id,
            "permissions": user.permissions,
            "settings": user.settings,
            "created_at": user.created_at.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None
        }
    except Exception as e:
        logger.error(f"Failed to get user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户信息失败"
        )


# ==================== 用户管理 CRUD（管理员） ====================

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str = "123456"
    role: str = "user"
    company_id: Optional[str] = None
    is_active: bool = True


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    role: Optional[str] = None
    company_id: Optional[str] = None
    is_active: Optional[bool] = None
    permissions: Optional[list] = None


class PasswordReset(BaseModel):
    password: str


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "role": u.role,
        "company_id": u.company_id,
        "is_active": u.is_active,
        "is_verified": u.is_verified,
        "permissions": u.permissions or [],
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }


@router.get("", response_model=List[dict])
def list_users(
    search: Optional[str] = Query(None, description="按邮箱/用户名搜索"),
    role: Optional[str] = Query(None, description="角色过滤"),
    is_active: Optional[bool] = Query(None, description="启用状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户列表（管理员）"""
    q = db.query(User)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(User.email.ilike(like), User.username.ilike(like)))
    if role:
        q = q.filter(User.role == role)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    total = q.count()
    items = q.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return [_user_to_dict(u) for u in items]


@router.post("", response_model=dict, status_code=201)
def create_user(
    data: UserCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """创建用户（管理员）"""
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="该邮箱已注册")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="该用户名已存在")
    u = User(
        id=str(uuid.uuid4()),
        email=data.email,
        username=data.username,
        hashed_password=_hash_password(data.password),
        role=data.role,
        company_id=data.company_id,
        is_active=data.is_active,
        is_verified=True,
        permissions=[],
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    result = _user_to_dict(u)
    result["temp_password"] = data.password
    return result


@router.put("/{user_id}", response_model=dict)
def update_user(
    user_id: str,
    data: UserUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新用户信息（管理员）"""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if data.email and data.email != u.email:
        if db.query(User).filter(User.email == data.email).first():
            raise HTTPException(status_code=400, detail="该邮箱已被其他用户使用")
        u.email = data.email
    if data.username and data.username != u.username:
        if db.query(User).filter(User.username == data.username).first():
            raise HTTPException(status_code=400, detail="该用户名已被其他用户使用")
        u.username = data.username
    for field in ("role", "company_id", "is_active", "permissions"):
        val = getattr(data, field)
        if val is not None:
            setattr(u, field, val)
    db.commit()
    return _user_to_dict(u)


@router.post("/{user_id}/reset-password", response_model=dict)
def reset_password(
    user_id: str,
    data: PasswordReset,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """重置用户密码（管理员）"""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    u.hashed_password = _hash_password(data.password)
    db.commit()
    return {"success": True, "message": "密码已重置"}


@router.post("/{user_id}/toggle-active", response_model=dict)
def toggle_active(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """启用/禁用用户（管理员）"""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    u.is_active = not u.is_active
    db.commit()
    return {"success": True, "is_active": u.is_active}


@router.delete("/{user_id}", response_model=dict)
def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除用户（管理员）"""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if u.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    db.delete(u)
    db.commit()
    return {"success": True}

