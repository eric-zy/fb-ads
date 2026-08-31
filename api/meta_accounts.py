"""
主账号（Business Manager / Meta 主号）管理 API
提供 BM 主账号的增删改查、设为默认（切换当前主账号）、
凭据健康状态、以及广告账户归属校验 / 同步。

**三层分离管理**（设计文档第 9 节）：
    BM 主账号（meta_accounts）
        ├─ 凭据（credentials，Access Token 加密存储）   ← Token 归凭据管
        └─ 广告账户（ad_accounts）                      ← 账户归 BM 管

BM 主表不再承担明文 Token 存储职责：接口传入的 access_token 会加密写入
credentials 表，BM 表只保留主数据。读取 Token 统一走
CredentialService.resolve_token_for_meta()。

权限：仅管理员。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import uuid

from config.settings import settings
from core.audit import record_audit
from core.database import get_db
from core.auth import require_admin
from core.enums import CredentialStatus
from core.logger import logger
from models import (
    AccountStatus,
    AdAccount,
    BusinessStatus,
    Credential,
    MetaAccount,
    MetaSyncLog,
    SystemStatus,
    User,
)
from services.credential_service import CredentialError, CredentialService
from services.fb_client import fb_client
from api.accounts import account_to_dict
from services.meta import BusinessService, MetaSyncService
from services.meta.ad_account_service import UNDEPLOYABLE_META_STATUS
from services.meta.errors import MetaApiError
from tasks.meta_sync_tasks import sync_ad_accounts_task, sync_business_task

router = APIRouter(prefix="/api/v1/meta-accounts", tags=["主账号管理"])


# ==================== 请求/响应模型 ====================

class MetaAccountCreate(BaseModel):
    name: str = Field(..., description="BM 显示名称")
    business_id: str = Field(..., description="Meta Business ID，唯一")
    access_token: Optional[str] = Field(None, description="BM 访问令牌（加密写入凭据表）")
    app_id: Optional[str] = None
    is_default: bool = False
    token_type: str = Field("USER", description="凭据类型 USER / SYSTEM_USER / PAGE")
    timezone: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    verify_before_save: bool = Field(
        True, description="保存前调用 Meta 校验 Business ID 是否有效"
    )


class MetaAccountUpdate(BaseModel):
    name: Optional[str] = None
    business_id: Optional[str] = None
    access_token: Optional[str] = Field(None, description="传入则轮换该 BM 的凭据")
    app_id: Optional[str] = None
    is_default: Optional[bool] = None
    status: Optional[str] = Field(None, description="ACTIVE / DISABLED / ARCHIVED")
    timezone: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None


class VerifyAccountRequest(BaseModel):
    meta_account_id: str = Field(..., description="主账号 ID")
    account_id: str = Field(..., description="待验证的广告账户 ID（act_xxxx）")


# ==================== 工具 ====================

def _get_meta_or_404(db: Session, meta_id: str) -> MetaAccount:
    meta = db.query(MetaAccount).filter(MetaAccount.id == meta_id).first()
    if not meta:
        raise HTTPException(status_code=404, detail="主账号不存在")
    return meta


def _credential_health(db: Session, meta_id: str) -> Dict[str, Any]:
    """汇总该 BM 的凭据健康状态（供列表页直接展示）"""
    cred = (
        db.query(Credential)
        .filter(Credential.meta_account_id == meta_id)
        .order_by(Credential.created_at.desc())
        .first()
    )
    if not cred:
        # V1 起 BM 主表不再存明文 Token，因此没有凭据记录就等于没有凭据
        return {
            "credential_id": None,
            "credential_status": "NONE",
            "credential_masked": None,
            "credential_expires_at": None,
            "credential_is_expired": False,
            "has_credential": False,
            "credential_source": "NONE",
        }

    return {
        "credential_id": cred.id,
        "credential_status": cred.status,
        "credential_masked": cred.to_dict().get("access_token_masked"),
        "credential_expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
        "credential_is_expired": cred.is_expired(),
        "has_credential": cred.status == CredentialStatus.ACTIVE.value,
        "credential_source": "CREDENTIALS",
    }


def _meta_to_dict(db: Session, meta: MetaAccount) -> Dict[str, Any]:
    return {**meta.to_dict(include_secret=False), **_credential_health(db, meta.id)}


def _resolve_token(db: Session, meta: MetaAccount) -> str:
    """解析该 BM 可用的明文 Token（凭据表优先，兼容历史明文）"""
    try:
        token, _ = CredentialService(db).resolve_token_for_meta(meta.id)
        return token
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 接口 ====================

@router.get("", response_model=List[dict])
def list_meta_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """列出所有主账号（含凭据健康状态，不返回敏感令牌）"""
    items = db.query(MetaAccount).order_by(MetaAccount.created_at.desc()).all()
    return [_meta_to_dict(db, m) for m in items]


@router.get("/default")
def get_default_meta_account(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """获取当前默认主账号"""
    m = db.query(MetaAccount).filter(MetaAccount.is_default == True).first()
    if not m:
        return {"meta_account": None}
    return {"meta_account": _meta_to_dict(db, m)}


@router.get("/{meta_id}", response_model=dict)
def get_meta_account(
    meta_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """主账号详情（含凭据健康状态与账户概况）"""
    meta = _get_meta_or_404(db, meta_id)
    data = _meta_to_dict(db, meta)

    accounts = db.query(AdAccount).filter(AdAccount.business_id == meta_id).all()
    data["accounts"] = [account_to_dict(a) for a in accounts]
    data["account_stats"] = {
        "total": len(accounts),
        "system_active": sum(
            1 for a in accounts if a.system_status == SystemStatus.ACTIVE.value
        ),
        "system_disabled": sum(
            1 for a in accounts if a.system_status == SystemStatus.DISABLED.value
        ),
        "meta_abnormal": sum(
            1
            for a in accounts
            if (a.account_status or "").strip().upper() in UNDEPLOYABLE_META_STATUS
        ),
    }
    return data


@router.post("", status_code=201)
def create_meta_account(
    payload: MetaAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """新增主账号（BM）—— 文档 §14 保存流程

    填写 → 验证 Credential → 调用 Meta 获取 Business → 校验 Business ID → 保存 → 同步账户

    access_token 不写入 BM 主表，而是加密存入 credentials 表；
    Token 的更换 / 失效只影响凭据记录，不动 BM 主数据。

    重复 Business ID 禁止创建。
    """
    if db.query(MetaAccount).filter(MetaAccount.business_id == payload.business_id).first():
        raise HTTPException(status_code=400, detail=f"BM ID {payload.business_id} 已存在")

    if payload.token_type not in ("USER", "SYSTEM_USER", "PAGE"):
        raise HTTPException(status_code=400, detail="token_type 只能是 USER / SYSTEM_USER / PAGE")

    meta = MetaAccount(
        id=str(uuid.uuid4()),
        name=payload.name,
        business_id=payload.business_id,
        app_id=payload.app_id,
        is_default=payload.is_default,
        timezone=payload.timezone,
        currency=payload.currency,
        description=payload.description,
    )
    if payload.is_default:
        db.query(MetaAccount).filter(MetaAccount.is_default == True).update({"is_default": False})
    db.add(meta)
    db.flush()

    # 明文 Token 加密写入凭据表
    if payload.access_token:
        try:
            CredentialService(db).create_for_meta(
                meta_account_id=meta.id,
                plain_token=payload.access_token,
                token_type=payload.token_type,
            )
        except CredentialError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    # 保存前校验 Business ID 是否真实有效（未配置 FB 凭据时自动降级放行）
    if payload.verify_before_save and payload.access_token:
        result = BusinessService(db).verify_connection(meta)
        if not result["ok"] and not result["dev_mode"]:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Business ID 校验未通过：{result.get('error')}",
            )
        if result["dev_mode"]:
            meta.last_sync_error = "开发模式：未配置 FB 凭据，跳过 Business ID 校验"

    db.commit()
    db.refresh(meta)

    record_audit(
        db,
        action="CREATE_META_ACCOUNT",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        request_data={"name": meta.name, "business_id": meta.business_id},
        request=request,
    )
    return _meta_to_dict(db, meta)


@router.put("/{meta_id}")
def update_meta_account(
    meta_id: str,
    payload: MetaAccountUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新主账号

    传入 access_token 表示轮换该 BM 的凭据（旧凭据保留为 DISABLED），
    不传则只更新主数据。
    """
    meta = _get_meta_or_404(db, meta_id)

    data = payload.model_dump(exclude_unset=True)
    new_token = data.pop("access_token", None)

    if "status" in data and data["status"] not in (s.value for s in BusinessStatus):
        raise HTTPException(
            status_code=400,
            detail=f"status 只能是 {' / '.join(s.value for s in BusinessStatus)}",
        )

    if "business_id" in data and data["business_id"] != meta.business_id:
        exist = (
            db.query(MetaAccount)
            .filter(MetaAccount.business_id == data["business_id"], MetaAccount.id != meta_id)
            .first()
        )
        if exist:
            raise HTTPException(status_code=400, detail="BM ID 已被其他主账号使用")

    if data.get("is_default") is True:
        db.query(MetaAccount).filter(MetaAccount.is_default == True).update({"is_default": False})

    for k, v in data.items():
        setattr(meta, k, v)

    # 轮换凭据（独立于主数据的更新）
    if new_token:
        try:
            CredentialService(db).create_for_meta(
                meta_account_id=meta.id,
                plain_token=new_token,
                token_type="USER",
            )
        except CredentialError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(meta)

    record_audit(
        db,
        action="UPDATE_META_ACCOUNT",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        request_data={**{k: v for k, v in data.items()}, "rotated_token": bool(new_token)},
        request=request,
    )
    return _meta_to_dict(db, meta)


@router.post("/{meta_id}/set-default")
def set_default_meta_account(
    meta_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """切换当前默认主账号"""
    meta = _get_meta_or_404(db, meta_id)
    db.query(MetaAccount).filter(MetaAccount.is_default == True).update({"is_default": False})
    meta.is_default = True
    db.commit()
    return {"success": True, "meta_account": _meta_to_dict(db, meta)}


@router.delete("/{meta_id}")
def delete_meta_account(
    meta_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除主账号（若该主账号下仍有广告账户则拒绝）

    同时清理该 BM 名下的凭据，避免留下无主凭据。
    """
    meta = _get_meta_or_404(db, meta_id)
    linked = db.query(AdAccount).filter(AdAccount.business_id == meta_id).count()
    if linked > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该主账号下仍有 {linked} 个广告账户，请先移除或转移后再删除",
        )
    db.query(Credential).filter(Credential.meta_account_id == meta_id).delete(
        synchronize_session=False
    )
    db.delete(meta)
    db.commit()

    record_audit(
        db,
        action="DELETE_META_ACCOUNT",
        resource_type="meta_account",
        resource_id=meta_id,
        user_id=current_user.id,
        request=request,
    )
    return {"success": True}


@router.post("/verify-account")
def verify_account(
    payload: VerifyAccountRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """验证某广告账户是否归属指定主账号（BM）

    添加广告账户前必须调用本接口，验证不通过不允许保存。
    Token 从凭据表解析（加密优先，兼容历史明文）。
    """
    meta = _get_meta_or_404(db, payload.meta_account_id)
    token = _resolve_token(db, meta)

    return fb_client.verify_account_under_bm(
        business_id=meta.business_id,
        access_token=token,
        target_account_id=payload.account_id,
    )


@router.get("/{meta_id}/credentials", response_model=List[dict])
def list_meta_credentials(
    meta_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """列出该 BM 名下的凭据（脱敏）"""
    _get_meta_or_404(db, meta_id)
    items = (
        db.query(Credential)
        .filter(Credential.meta_account_id == meta_id)
        .order_by(Credential.created_at.desc())
        .all()
    )
    return [c.to_dict() for c in items]


@router.post("/{meta_id}/rotate-token")
def rotate_meta_token(
    meta_id: str,
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """轮换该 BM 的 Access Token

    请求体：{"access_token": "新的明文 Token", "token_type": "USER"}
    旧凭据保留为 DISABLED，便于回溯。
    """
    meta = _get_meta_or_404(db, meta_id)

    new_token = (payload or {}).get("access_token")
    if not new_token:
        raise HTTPException(status_code=400, detail="access_token 不能为空")
    token_type = (payload or {}).get("token_type") or "USER"
    if token_type not in ("USER", "SYSTEM_USER", "PAGE"):
        raise HTTPException(status_code=400, detail="token_type 只能是 USER / SYSTEM_USER / PAGE")

    try:
        cred = CredentialService(db).create_for_meta(
            meta_account_id=meta.id,
            plain_token=new_token,
            token_type=token_type,
        )
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))

    record_audit(
        db,
        action="ROTATE_META_TOKEN",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        request_data={"token_type": token_type},
        request=request,
    )
    return _meta_to_dict(db, meta) | {"credential_id": cred.id}


@router.post("/{meta_id}/sync-accounts")
def sync_meta_accounts(
    meta_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """异步同步该 BM 下的广告账户（文档 §23 / §25）

    HTTP 不等待 Meta API：立即返回 job_id，由 Celery Worker 执行。

    Upsert 规则（文档 §24）：
        - 唯一键 (business_id, account_id)
        - 已存在则 UPDATE，不存在则 INSERT
        - **不会覆盖 system_status**，管理员的禁用决定保留
        - Meta 不再返回的账户不会自动删除

    进度与结果通过 `GET /{meta_id}/sync-logs` 查询。
    """
    meta = _get_meta_or_404(db, meta_id)
    # 提前校验凭据可用性，避免投递一个注定失败的任务
    _resolve_token(db, meta)

    async_result = sync_ad_accounts_task.delay(meta.id)

    record_audit(
        db,
        action="SYNC_META_ACCOUNTS",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        response_data={"celery_task_id": async_result.id},
        request=request,
    )
    logger.info(
        f"[meta-accounts] 已提交 BM {meta.business_id} 的账户同步任务: {async_result.id}"
    )

    return {
        "success": True,
        "job_id": async_result.id,
        "status": "QUEUED",
        "message": "同步任务已提交，请通过 /sync-logs 查询结果",
    }


@router.get("/{meta_id}/ad-accounts/from-meta", response_model=dict)
def list_ad_accounts_from_meta(
    meta_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """拉取该 BM 在 Meta 侧的账户列表（**不入库**，供导入前勾选）

    文档 §17 导入流程：选择 BM → 从 Meta 同步 → 展示 → 勾选 → 导入。
    """
    meta = _get_meta_or_404(db, meta_id)
    try:
        raw = MetaSyncService(db).fetch_ad_accounts_from_meta(meta.id)
    except MetaApiError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = {
        a.account_id for a in db.query(AdAccount).filter(AdAccount.business_id == meta_id).all()
    }
    accounts = []
    for item in raw:
        account_id = str(item.get("id", "")).strip()
        if account_id and not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        accounts.append(
            {
                "id": account_id,
                "name": item.get("name"),
                "account_status": (
                    str(item.get("account_status"))
                    if item.get("account_status") is not None
                    else None
                ),
                "currency": item.get("currency"),
                "_existing": account_id in existing,
            }
        )

    return {
        "dev_mode": not settings.FB_ACCESS_TOKEN,
        "total": len(accounts),
        "accounts": accounts,
    }


class ImportAccountsRequest(BaseModel):
    account_ids: List[str] = Field(..., description="勾选的 Meta 账户 ID，如 act_111")


@router.post("/{meta_id}/ad-accounts/import", response_model=dict)
def import_ad_accounts(
    meta_id: str,
    payload: ImportAccountsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """按勾选结果导入账户（文档 §17）

    Upsert 语义：已存在则更新 Meta 侧字段，不存在则创建；
    **不覆盖 system_status**（管理员的停用决定保留）。
    """
    _get_meta_or_404(db, meta_id)
    if not payload.account_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个账户")

    log = MetaSyncService(db).import_ad_accounts(meta_id, payload.account_ids)

    record_audit(
        db,
        action="IMPORT_AD_ACCOUNTS",
        resource_type="meta_account",
        resource_id=meta_id,
        user_id=current_user.id,
        request_data={"count": len(payload.account_ids)},
        response_data=log.to_dict(),
        request=request,
    )

    return {
        "success": log.failed_count == 0,
        "sync_log": log.to_dict(),
        "success_count": log.success_count,
        "failed_count": log.failed_count,
    }


@router.get("/{meta_id}/sync-logs", response_model=List[dict])
def list_sync_logs(
    meta_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """该 BM 的同步日志（文档 §10，与操作审计 audit_logs 分开）"""
    _get_meta_or_404(db, meta_id)
    logs = (
        db.query(MetaSyncLog)
        .filter(MetaSyncLog.business_id == meta_id)
        .order_by(MetaSyncLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [log.to_dict() for log in logs]


@router.post("/{meta_id}/verify")
def verify_meta_account(
    meta_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """验证该 BM 与其凭据能否连通 Meta（文档 §14 的"验证连接"）"""
    meta = _get_meta_or_404(db, meta_id)
    return BusinessService(db).verify_connection(meta)


@router.post("/{meta_id}/disable")
def disable_meta_account(
    meta_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """禁用 BM（文档 §20）

    BM 置为 DISABLED 后，其下账户不再进入可投放账户池
    （见 /api/v1/accounts/available-for-deployment）。
    """
    meta = _get_meta_or_404(db, meta_id)
    meta.status = BusinessStatus.DISABLED.value
    db.commit()

    record_audit(
        db,
        action="DISABLE_META_ACCOUNT",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        request=request,
    )
    return _meta_to_dict(db, meta)


@router.post("/{meta_id}/archive")
def archive_meta_account(
    meta_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """归档 BM（文档 §20）

    归档是不可再用状态，通常在该 BM 已废弃时使用；如需恢复请先改为 ACTIVE。
    """
    meta = _get_meta_or_404(db, meta_id)
    meta.status = BusinessStatus.ARCHIVED.value
    db.commit()

    record_audit(
        db,
        action="ARCHIVE_META_ACCOUNT",
        resource_type="meta_account",
        resource_id=meta.id,
        user_id=current_user.id,
        request=request,
    )
    return _meta_to_dict(db, meta)
