"""租户管理 API（SaaS 多租户）

权限矩阵：
    GET    /api/v1/tenants/current          租户成员      查看自己所属租户
    PATCH  /api/v1/tenants/current          租户管理员    修改租户资料/设置
    GET    /api/v1/tenants                  平台管理员    租户列表
    POST   /api/v1/tenants                  平台管理员    开通租户（含管理员账号）
    POST   /api/v1/tenants/{id}/status      平台管理员    启停/归档
    GET    /api/v1/tenants/{id}/usage       平台管理员    配额用量

说明：`Tenant` 本身**不继承** `TenantMixin`（它是隔离的根节点而非被隔离对象），
因此平台侧接口无需 `bypass_tenant` 即可查询；而创建租户下的 User 时，
必须显式传入 `tenant_id`（创建者上下文是平台，不属于该租户）。
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.auth import get_current_active_user, get_current_tenant, require_platform_admin
from core.database import get_db
from core.tenant import bypass_tenant
from models import AdAccount, CampaignTemplate, MetaAccount, Tenant, User
from models.tenant import TenantStatus, UserRole

router = APIRouter(prefix="/api/v1/tenants", tags=["租户管理"])


# ==================== 请求模型 ====================

class TenantCreate(BaseModel):
    name: str = Field(..., description="租户名称（公司/团队）")
    slug: str = Field(..., description="租户唯一标识，如 acme（用于子域名/登录组织码）")
    plan: str = "FREE"
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None

    # 初始管理员账号
    admin_email: EmailStr
    admin_username: Optional[str] = None
    admin_password: str = "123456"

    max_users: Optional[int] = None
    max_meta_accounts: Optional[int] = None
    max_ad_accounts: Optional[int] = None
    max_templates: Optional[int] = None


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    settings: Optional[Dict[str, Any]] = None
    features: Optional[Dict[str, Any]] = None


class TenantStatusUpdate(BaseModel):
    status: str = Field(..., description="ACTIVE / SUSPENDED / ARCHIVED")
    reason: Optional[str] = None


# ==================== 租户侧：当前租户 ====================

@router.get("/current", response_model=dict)
def get_current_tenant_info(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """当前登录用户所属租户"""
    data = tenant.to_dict()
    data["member_count"] = (
        db.query(func.count(User.id)).filter(User.tenant_id == tenant.id).scalar() or 0
    )
    return data


@router.patch("/current", response_model=dict)
def update_current_tenant(
    req: TenantUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """修改当前租户资料（仅租户管理员）"""
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="仅租户管理员可修改租户资料")

    for field in ("name", "contact_name", "contact_email"):
        value = getattr(req, field)
        if value is not None:
            setattr(tenant, field, value)
    if req.settings is not None:
        tenant.settings = {**(tenant.settings or {}), **req.settings}
    if req.features is not None:
        tenant.features = {**(tenant.features or {}), **req.features}

    db.commit()
    db.refresh(tenant)
    return tenant.to_dict()


# ==================== 平台侧：租户管理 ====================

@router.get("", response_model=List[dict])
def list_tenants(
    keyword: Optional[str] = Query(None, description="按名称/slug 搜索"),
    status_filter: Optional[str] = Query(None, alias="status", description="按状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """租户列表（平台管理员）"""
    q = db.query(Tenant)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Tenant.name.ilike(like) | Tenant.slug.ilike(like))
    if status_filter:
        q = q.filter(Tenant.status == status_filter)

    items = q.order_by(Tenant.created_at.desc()) \
             .offset((page - 1) * page_size).limit(page_size).all()
    return [t.to_dict() for t in items]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_tenant(
    req: TenantCreate,
    current_user: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """开通新租户，并自动创建其管理员账号

    事务：租户 + 管理员账号要么都成功，要么都回滚，
    避免"有租户没管理员"导致该租户永不可用。
    """
    normalized_slug = req.slug.strip().lower()
    if db.query(Tenant).filter(Tenant.slug == normalized_slug).first():
        raise HTTPException(status_code=400, detail=f"租户标识已存在: {normalized_slug}")
    if db.query(User).filter(User.email == req.admin_email).first():
        raise HTTPException(status_code=400, detail=f"管理员邮箱已注册: {req.admin_email}")

    tenant = Tenant(
        id=uuid.uuid4().hex,
        name=req.name,
        slug=normalized_slug,
        status=TenantStatus.ACTIVE.value,
        plan=req.plan,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
        max_users=req.max_users,
        max_meta_accounts=req.max_meta_accounts,
        max_ad_accounts=req.max_ad_accounts,
        max_templates=req.max_templates,
        features={},
        settings={},
    )
    db.add(tenant)
    db.flush()  # 拿到 tenant.id 用于创建管理员

    admin = User(
        id=uuid.uuid4().hex,
        email=req.admin_email,
        username=req.admin_username or req.admin_email.split("@")[0],
        hashed_password=_sha256(req.admin_password),
        tenant_id=tenant.id,  # 显式指定：当前上下文是平台而非该租户
        role=UserRole.TENANT_ADMIN.value,
        is_active=True,
        is_verified=True,
        permissions=[],
        settings={},
    )
    db.add(admin)
    db.flush()

    tenant.owner_user_id = admin.id
    db.commit()
    db.refresh(tenant)

    return {
        **tenant.to_dict(),
        "admin": {
            "id": admin.id,
            "email": admin.email,
            "username": admin.username,
            "role": admin.role,
            "temp_password": req.admin_password,
        },
    }


@router.post("/{tenant_id}/status", response_model=dict)
def update_tenant_status(
    tenant_id: str,
    req: TenantStatusUpdate,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """启用 / 停用 / 归档租户"""
    if req.status not in {s.value for s in TenantStatus}:
        raise HTTPException(
            status_code=400,
            detail=f"非法状态: {req.status}，可选 {[s.value for s in TenantStatus]}",
        )
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    tenant.status = req.status
    db.commit()
    return {"id": tenant_id, "status": tenant.status, "reason": req.reason}


@router.get("/{tenant_id}/usage", response_model=dict)
def get_tenant_usage(
    tenant_id: str,
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """租户配额用量统计（跨租户聚合，需绕过来宾过滤）"""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="租户不存在")

    with bypass_tenant():
        used = {
            "users": db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0,
            "meta_accounts": db.query(func.count(MetaAccount.id)).filter(MetaAccount.tenant_id == tenant_id).scalar() or 0,
            "ad_accounts": db.query(func.count(AdAccount.id)).filter(AdAccount.tenant_id == tenant_id).scalar() or 0,
            "templates": db.query(func.count(CampaignTemplate.id)).filter(CampaignTemplate.tenant_id == tenant_id).scalar() or 0,
        }

    return {
        "tenant_id": tenant_id,
        "used": used,
        "quota": {f"max_{k}": getattr(tenant, f"max_{k}", None) for k in used},
        # 已超配额的维度（配额为 None 表示不限，永远不算超）
        "exceeded": [k for k, v in used.items() if not tenant.check_quota(f"max_{k}", v)],
    }


def _sha256(password: str) -> str:
    """与 core.auth.AuthManager 一致的密码哈希"""
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()
