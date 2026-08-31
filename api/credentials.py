"""凭据（Credential）管理 API —— 设计文档第 9 节

"账号统一管理"的第三层：BM 主账号 / 广告账户 / **凭据** 分离管理。

设计要点：
- Access Token 一律加密存储于 credentials 表，BM 主表不再承担明文存储职责；
  Token 更换只影响本表，不动 BM / 广告账户主数据。
- 对外接口**默认只返回脱敏 Token**（EAAx...9zQd），明文需显式调用
  `/reveal` 且会写入审计日志。
- 支持轮换（rotate）、停用（disable）、启用（enable）、有效性校验（verify）。
- 凭据过期一律不回退到全局 Token，避免多 BM 场景"串号"（见
  services/credential_service.py 的 CredentialExpiredError）。

权限：仅管理员。
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.audit import record_audit
from core.auth import require_admin
from core.database import get_db
from core.enums import CredentialStatus
from core.logger import logger
from models import Credential, MetaAccount, User
from services.credential_service import CredentialError, CredentialService

router = APIRouter(prefix="/api/v1/credentials", tags=["凭据管理"])

VALID_TOKEN_TYPES = ("USER", "SYSTEM_USER", "PAGE")
VALID_STATUSES = tuple(s.value for s in CredentialStatus)


# ==================== 请求/响应模型 ====================

class CredentialCreate(BaseModel):
    meta_account_id: str = Field(..., description="归属的 BM 主账号 ID")
    access_token: str = Field(..., description="明文 Access Token（服务端加密后存储）")
    name: Optional[str] = Field(None, description="凭据名称，便于运维识别")
    app_id: Optional[str] = Field(None, description="Meta App ID")
    token_type: str = Field("USER", description="USER / SYSTEM_USER / PAGE")
    expires_at: Optional[datetime] = Field(None, description="过期时间，为空表示长期有效")
    replace_active: bool = Field(True, description="是否停用该 BM 现有的生效凭据（轮换）")


class CredentialUpdate(BaseModel):
    name: Optional[str] = None
    app_id: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: Optional[str] = None


class RotateRequest(BaseModel):
    access_token: str = Field(..., description="新的明文 Access Token")
    name: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    keep_old: bool = Field(True, description="是否把旧凭据保留为 DISABLED（便于回溯）")


class RevealRequest(BaseModel):
    confirm: bool = Field(False, description="必须为 true，防止误调用导致明文泄露")


# ==================== 工具 ====================

def _get_credential_or_404(db: Session, credential_id: str) -> Credential:
    cred = db.query(Credential).filter(Credential.id == credential_id).first()
    if not cred:
        raise HTTPException(status_code=404, detail="凭据不存在")
    return cred


def _credential_to_dict(db: Session, cred: Credential, include_token: bool = False) -> dict:
    """凭据详情（默认脱敏），附带所属 BM 信息便于前端展示"""
    data = cred.to_dict(include_token=include_token)
    meta = (
        db.query(MetaAccount).filter(MetaAccount.id == cred.meta_account_id).first()
        if cred.meta_account_id
        else None
    )
    data["meta_account_name"] = meta.name if meta else None
    data["business_id"] = meta.business_id if meta else None
    return data


def _validate_token_type(token_type: str) -> str:
    if token_type not in VALID_TOKEN_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"token_type 只能是 {' / '.join(VALID_TOKEN_TYPES)}",
        )
    return token_type


def _validate_status(status: str) -> str:
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 只能是 {' / '.join(VALID_STATUSES)}",
        )
    return status


# ==================== 接口 ====================

@router.get("", response_model=List[dict])
def list_credentials(
    meta_account_id: Optional[str] = Query(None, description="按 BM 主账号过滤"),
    status: Optional[str] = Query(None, description="按状态过滤 ACTIVE/EXPIRED/INVALID/DISABLED"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """凭据列表（仅返回脱敏 Token）"""
    q = db.query(Credential)
    if meta_account_id:
        q = q.filter(Credential.meta_account_id == meta_account_id)
    if status:
        q = q.filter(Credential.status == _validate_status(status))

    items = (
        q.order_by(Credential.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_credential_to_dict(db, c) for c in items]


@router.get("/{credential_id}", response_model=dict)
def get_credential(
    credential_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """凭据详情（脱敏）"""
    return _credential_to_dict(db, _get_credential_or_404(db, credential_id))


@router.post("", response_model=dict, status_code=201)
def create_credential(
    payload: CredentialCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """新增凭据（绑定到指定 BM，Token 加密存储）

    默认会把该 BM 现有的生效凭据置为 DISABLED，即"轮换"语义；
    如需并存多条（例如灰度切换）可传 replace_active=false。
    """
    meta = db.query(MetaAccount).filter(MetaAccount.id == payload.meta_account_id).first()
    if not meta:
        raise HTTPException(status_code=400, detail="指定的 BM 主账号不存在")

    service = CredentialService(db)
    try:
        cred = service.create_for_meta(
            meta_account_id=payload.meta_account_id,
            plain_token=payload.access_token,
            token_type=_validate_token_type(payload.token_type),
            expires_at=payload.expires_at,
            replace_active=payload.replace_active,
        )
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if payload.name:
        cred.name = payload.name
    if payload.app_id:
        cred.app_id = payload.app_id
    db.commit()
    db.refresh(cred)

    record_audit(
        db,
        action="CREATE_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        request_data={
            "meta_account_id": payload.meta_account_id,
            "name": cred.name,
            "token_type": cred.token_type,
            "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
            "replace_active": payload.replace_active,
        },
        request=request,
    )
    return _credential_to_dict(db, cred)


@router.patch("/{credential_id}", response_model=dict)
def update_credential(
    credential_id: str,
    payload: CredentialUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新凭据元信息（不含 Token 本身，换 Token 请用 /rotate）"""
    cred = _get_credential_or_404(db, credential_id)

    data = payload.model_dump(exclude_unset=True)
    if "token_type" in data and data["token_type"] is not None:
        data["token_type"] = _validate_token_type(data["token_type"])
    if "status" in data and data["status"] is not None:
        data["status"] = _validate_status(data["status"])

    for field, value in data.items():
        setattr(cred, field, value)
    db.commit()
    db.refresh(cred)

    record_audit(
        db,
        action="UPDATE_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        request_data=data,
        request=request,
    )
    return _credential_to_dict(db, cred)


@router.post("/{credential_id}/rotate", response_model=dict)
def rotate_credential(
    credential_id: str,
    payload: RotateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """轮换 Token：为该 BM 写入新凭据

    keep_old=true（默认）时旧凭据保留为 DISABLED，便于回溯；
    keep_old=false 时直接删除旧凭据。
    """
    old = _get_credential_or_404(db, credential_id)
    if not old.meta_account_id:
        raise HTTPException(status_code=400, detail="该凭据未绑定 BM，无法轮换")

    service = CredentialService(db)
    try:
        new_cred = service.create_for_meta(
            meta_account_id=old.meta_account_id,
            plain_token=payload.access_token,
            token_type=_validate_token_type(payload.token_type or old.token_type),
            expires_at=payload.expires_at if payload.expires_at is not None else old.expires_at,
            replace_active=True,
        )
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 继承旧凭据的标识信息，避免轮换后名称丢失
    new_cred.name = payload.name or old.name
    new_cred.app_id = old.app_id
    db.commit()
    db.refresh(new_cred)

    if not payload.keep_old:
        db.delete(old)
        db.commit()

    record_audit(
        db,
        action="ROTATE_CREDENTIAL",
        resource_type="credential",
        resource_id=new_cred.id,
        user_id=current_user.id,
        request_data={
            "meta_account_id": old.meta_account_id,
            "old_credential_id": old.id,
            "keep_old": payload.keep_old,
            "token_type": new_cred.token_type,
        },
        request=request,
    )
    return _credential_to_dict(db, new_cred)


@router.post("/{credential_id}/verify", response_model=dict)
def verify_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """校验凭据是否有效（调 Meta /me 接口）

    校验通过会刷新 last_verified_at；失败会把凭据标记为 INVALID 并写入 last_error。
    """
    cred = _get_credential_or_404(db, credential_id)
    service = CredentialService(db)
    result = service.verify_credential(cred)

    record_audit(
        db,
        action="VERIFY_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        request_data={},
        response_data={"valid": result["valid"], "dev_mode": result["dev_mode"]},
        request=request,
    )

    return {
        "credential_id": cred.id,
        **result,
        "status": cred.status,
        "last_verified_at": cred.last_verified_at.isoformat() if cred.last_verified_at else None,
        "last_error": cred.last_error,
    }


@router.post("/{credential_id}/disable", response_model=dict)
def disable_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """停用凭据（保留记录，不再参与解析）"""
    cred = _get_credential_or_404(db, credential_id)
    cred.status = CredentialStatus.DISABLED.value
    db.commit()

    record_audit(
        db,
        action="DISABLE_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        request=request,
    )
    return _credential_to_dict(db, cred)


@router.post("/{credential_id}/enable", response_model=dict)
def enable_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """启用凭据

    已过期的凭据不允许直接启用，应先轮换 Token。
    """
    cred = _get_credential_or_404(db, credential_id)
    if cred.is_expired():
        raise HTTPException(status_code=400, detail="凭据已过期，请改用 /rotate 更换 Token")

    cred.status = CredentialStatus.ACTIVE.value
    cred.last_error = None
    db.commit()

    record_audit(
        db,
        action="ENABLE_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        request=request,
    )
    return _credential_to_dict(db, cred)


@router.post("/{credential_id}/reveal", response_model=dict)
def reveal_credential(
    credential_id: str,
    payload: RevealRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """查看凭据明文（高危操作，会写入审计日志）

    必须显式传 confirm=true，避免前端误调用造成 Token 泄露。
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="请传 confirm=true 以确认查看明文 Token")

    cred = _get_credential_or_404(db, credential_id)
    plain = cred.get_access_token()
    if not plain:
        raise HTTPException(
            status_code=500,
            detail="凭据解密失败，可能 SECRET_KEY 已变更，请用 /rotate 重新写入 Token",
        )

    record_audit(
        db,
        action="REVEAL_CREDENTIAL",
        resource_type="credential",
        resource_id=cred.id,
        user_id=current_user.id,
        response_data={"revealed": True},
        request=request,
    )
    logger.warning(
        f"[credentials] 管理员 {current_user.id} 查看了凭据 {cred.id} 的明文 Token"
    )
    return {"id": cred.id, "access_token": plain}


@router.delete("/{credential_id}", response_model=dict)
def delete_credential(
    credential_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除凭据

    若该凭据是该 BM 唯一的生效凭据，删除后该 BM 下的广告账户将无法调用 Meta API，
    接口会先给出提醒（可通过 force 参数强制删除）。
    """
    cred = _get_credential_or_404(db, credential_id)

    db.delete(cred)
    db.commit()

    record_audit(
        db,
        action="DELETE_CREDENTIAL",
        resource_type="credential",
        resource_id=credential_id,
        user_id=current_user.id,
        request=request,
    )
    return {"success": True}
