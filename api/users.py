# ==================== 用户管理API端点 ====================

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import List

from core.database import get_db
from core.logger import logger
from models import User, AdAccount

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# ==================== 数据模型 ====================

class UserSettingsUpdate(BaseModel):
    """用户设置更新"""
    settings: dict

class AccountResponse(BaseModel):
    """账户响应"""
    id: str
    account_id: str
    account_name: str
    currency: str
    status: str
    daily_spend_limit: float
    risk_score: float
    is_frozen: bool

    class Config:
        from_attributes = True

class UserAccountsResponse(BaseModel):
    """用户账户列表响应"""
    accounts: List[AccountResponse]

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
            accounts=[AccountResponse.model_validate(a) for a in accounts]
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
