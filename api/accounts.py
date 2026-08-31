"""
广告账户 API（Meta 账号管理 V1 —— 设计文档 §6 / §7）

**三层分离管理**：
    BM 主账号（meta_accounts）─ 凭据（credentials，加密）─ 广告账户（ad_accounts）

广告账户只保存"归属哪个 BM"（business_id），不保存任何 Token；
调用 Meta API 所需的 Token 由 CredentialService 按所属 BM 解析。

状态约定（文档 §7）：
    account_status / effective_status —— Meta 侧状态，由同步覆盖
    system_status                     —— 系统侧状态，同步绝不能覆盖

金额约定（文档 §9）：
    一律最小货币单位（BIGINT）。$10.50 → 1050。换算见 core/money.py。

权限：管理员可操作全部账户；普通用户仅能查看分配给自己的账户。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import uuid

from core.audit import record_audit
from core.database import get_db
from core.auth import get_current_active_user, require_admin
from core.logger import logger
from models import (
    AdAccount, User, UserAccount, MetaAccount, SystemStatus,
    RiskEvent, RiskLevel, CampaignJobItem, MetaSyncLog,
)
from services.credential_service import CredentialError, CredentialService
from services.fb_client import fb_client
from services.meta import AdAccountService

router = APIRouter(prefix="/api/v1/accounts", tags=["账户管理"])


# ==================== 请求/响应模型 ====================

class AccountCreate(BaseModel):
    business_id: str = Field(..., description="归属 BM（meta_accounts.id），必填")
    account_id: str = Field(..., description="Meta 广告账户 ID（act_xxxx）")
    account_name: Optional[str] = None
    account_status: Optional[str] = Field(None, description="Meta 侧状态，通常由同步写入")
    currency: str = "USD"
    timezone: Optional[str] = None
    system_status: str = Field(SystemStatus.ACTIVE.value, description="ACTIVE / DISABLED")
    daily_spend_limit: int = Field(0, description="日限额，最小货币单位")
    monthly_spend_limit: int = Field(0, description="月限额，最小货币单位")
    risk_score: float = 0
    skip_verification: bool = Field(False, description="跳过 Meta 归属校验（应急开关）")


class AccountUpdate(BaseModel):
    account_name: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None
    system_status: Optional[str] = Field(None, description="ACTIVE / DISABLED")
    system_status_reason: Optional[str] = None
    daily_spend_limit: Optional[int] = Field(None, description="日限额，最小货币单位")
    monthly_spend_limit: Optional[int] = Field(None, description="月限额，最小货币单位")
    risk_score: Optional[float] = None
    business_id: Optional[str] = Field(
        None, description="变更归属的 BM（会先验证归属，验证不通过不生效）"
    )
    skip_verification: bool = Field(False, description="变更归属时跳过 Meta 校验")


class TransferRequest(BaseModel):
    # 刻意允许 null 传入：由业务层返回明确的中文提示，
    # 而不是让 Pydantic 抛 422（前端拿不到可读原因）
    business_id: Optional[str] = Field(
        None, description="目标 BM ID（必填；V1 不允许解除归属）"
    )
    skip_verification: bool = Field(
        False, description="跳过 Meta 归属校验（仅当 BM 凭据不可用时的应急开关）"
    )


class BulkRequest(BaseModel):
    action: str = Field(..., description="freeze / unfreeze / delete / transfer")
    account_ids: List[str] = Field(..., description="账户 ID（主键）列表")
    reason: Optional[str] = Field(None, description="冻结原因（action=freeze 时生效）")
    business_id: Optional[str] = Field(
        None, description="目标 BM（action=transfer 时生效，必填）"
    )
    skip_verification: bool = Field(False, description="action=transfer 时跳过归属校验")


class AssignUsers(BaseModel):
    user_ids: List[str] = Field(..., description="要分配的用户 ID 列表")


def _resolve_bm_token(db: Session, meta: MetaAccount) -> str:
    """解析 BM 可用的明文 Token（凭据表优先，兼容历史明文）"""
    try:
        token, _ = CredentialService(db).resolve_token_for_meta(meta.id)
        return token
    except CredentialError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _verify_bm_ownership(
    db: Session, meta: MetaAccount, account_id: str
) -> Optional[str]:
    """校验广告账户归属该 BM，返回 FB 侧账户名

    验证不通过直接抛 400；调用 Meta 失败同样视为不通过（安全默认值）。
    """
    token = _resolve_bm_token(db, meta)
    result = fb_client.verify_account_under_bm(
        business_id=meta.business_id,
        access_token=token,
        target_account_id=account_id,
    )
    if not result.get("verified"):
        raise HTTPException(
            status_code=400,
            detail=f"验证未通过，广告账户未归属该主账号（BM）：{result.get('error')}",
        )
    return result.get("account_name")


def _apply_meta_transfer(
    db: Session,
    account: AdAccount,
    target_business_id: Optional[str],
    skip_verification: bool = False,
) -> None:
    """变更广告账户的 BM 归属

    默认先调用 Meta 校验该账户确实在目标 BM 下，校验不通过不写库。
    skip_verification 仅用于 BM 凭据失效时的应急转移，需调用方显式开启。

    注意：V1 中 business_id 为 NOT NULL，因此不做"解除归属"（传空即拒绝）。
    """
    target_business_id = (target_business_id or "").strip() or None

    if not target_business_id:
        raise HTTPException(
            status_code=400,
            detail="广告账户必须归属某个 BM；如需停用请改用 system_status=DISABLED",
        )

    if target_business_id == account.business_id:
        return  # 归属未变化，无需校验

    meta = db.query(MetaAccount).filter(MetaAccount.id == target_business_id).first()
    if not meta:
        raise HTTPException(status_code=400, detail="指定的主账号不存在")
    if not skip_verification:
        _verify_bm_ownership(db, meta, account.account_id)

    # 同一 BM 内账户唯一；跨 BM 允许同一 act_xxx
    dup = (
        db.query(AdAccount)
        .filter(
            AdAccount.business_id == target_business_id,
            AdAccount.account_id == account.account_id,
            AdAccount.id != account.id,
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=400,
            detail=f"该 BM 下已存在账户 {account.account_id}，不允许重复",
        )

    account.business_id = target_business_id


def account_to_dict(a: AdAccount) -> dict:
    """账户统一序列化出口

    所有返回账户信息的接口（/accounts、/users/{id}/accounts 等）必须复用本函数，
    避免出现"同一资源两套字段契约"的问题（前端类型与实际响应对不上）。
    """
    return {
        "id": a.id,
        "account_id": a.account_id,
        "account_name": a.account_name,
        "currency": a.currency,
        "timezone": a.timezone,
        # ---- 归属 BM ----
        "business_id": a.business_id,
        "business_name": a.business.name if a.business else None,
        # ---- Meta 侧状态（同步覆盖） ----
        "account_status": a.account_status,
        "effective_status": a.effective_status,
        "disable_reason": a.disable_reason,
        # ---- 系统侧状态（同步不覆盖） ----
        "system_status": a.system_status,
        "system_status_reason": a.system_status_reason,
        "system_status_at": a.system_status_at.isoformat() if a.system_status_at else None,
        "capabilities": a.capabilities or {},
        # ---- 金额（最小货币单位） ----
        "spend_cap": a.spend_cap or 0,
        "amount_spent": a.amount_spent or 0,
        "balance": a.balance or 0,
        "daily_spend_limit": a.daily_spend_limit or 0,
        "monthly_spend_limit": a.monthly_spend_limit or 0,
        # ---- 风控 / 同步 ----
        "risk_score": a.risk_score,
        "last_risk_check": a.last_risk_check.isoformat() if a.last_risk_check else None,
        "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
        "last_sync_error": a.last_sync_error,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


# ==================== 接口 ====================

@router.get("", response_model=List[dict])
def list_accounts(
    response: Response,
    search: Optional[str] = Query(None, description="按账户名/ID 搜索"),
    system_status: Optional[str] = Query(None, description="系统状态过滤 ACTIVE / DISABLED"),
    account_status: Optional[str] = Query(None, description="Meta 侧状态过滤"),
    business_id: Optional[str] = Query(None, description="按归属的 BM 过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """账户列表（管理员看全部；普通用户只看分配给自己的）

    总数通过响应头 `X-Total-Count` 返回（保持响应体为数组，兼容既有前端）。
    """
    q = db.query(AdAccount)
    if current_user.role != "admin":
        sub = db.query(UserAccount.account_id).filter(UserAccount.user_id == current_user.id)
        q = q.filter(AdAccount.id.in_(sub))
    if search:
        like = f"%{search}%"
        q = q.filter(or_(
            AdAccount.account_name.ilike(like),
            AdAccount.account_id.ilike(like),
        ))
    if system_status:
        q = q.filter(AdAccount.system_status == system_status)
    if account_status:
        q = q.filter(AdAccount.account_status == account_status)
    if business_id:
        q = q.filter(AdAccount.business_id == business_id)

    total = q.count()
    items = (
        q.order_by(AdAccount.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    response.headers["X-Total-Count"] = str(total)
    return [account_to_dict(a) for a in items]


@router.get("/available-for-deployment", response_model=dict)
def list_available_for_deployment(
    business_id: Optional[str] = Query(None, description="按归属 BM 过滤"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """可参与批量投放的账户列表（文档 §19）

    判断规则（BM 启用 + 系统状态 ACTIVE + 凭据有效 + Meta 状态允许）
    **全部由后端 AdAccountService 计算**，前端不要自行拼接条件。

    返回结果自带 BM 与凭据上下文（脱敏），投放模块可直接用于创建批量任务。
    """
    items = AdAccountService(db).list_available(business_id=business_id)
    return {"total": len(items), "accounts": items}


@router.get("/{account_pk}", response_model=dict)
def get_account(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    if current_user.role != "admin":
        linked = db.query(UserAccount).filter(
            UserAccount.user_id == current_user.id,
            UserAccount.account_id == a.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=403, detail="无权访问该账户")
    return account_to_dict(a)


@router.post("", response_model=dict, status_code=201)
def create_account(
    data: AccountCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """创建广告账户（管理员）

    归属 BM（business_id）必填，且默认先调用 Meta 校验该账户确实在此 BM 下，
    校验不通过不落库。校验用的 Token 由 CredentialService 按 BM 解析。

    唯一键为 (business_id, account_id)，因此同一 act_xxx 可以挂到不同 BM。
    """
    data.business_id = (data.business_id or "").strip()
    if not data.business_id:
        raise HTTPException(status_code=400, detail="business_id 不能为空")

    meta = db.query(MetaAccount).filter(MetaAccount.id == data.business_id).first()
    if not meta:
        raise HTTPException(status_code=400, detail="指定的主账号不存在")

    # 同一 BM 内不允许重复
    dup = (
        db.query(AdAccount)
        .filter(
            AdAccount.business_id == data.business_id,
            AdAccount.account_id == data.account_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(
            status_code=400, detail=f"该 BM 下已存在账户 {data.account_id}"
        )

    account_name = data.account_name
    if not data.skip_verification:
        fb_name = _verify_bm_ownership(db, meta, data.account_id)
        # 若 FB 返回了账户名且前端未填写，则自动补全
        if fb_name and not account_name:
            account_name = fb_name

    if data.system_status not in (s.value for s in SystemStatus):
        raise HTTPException(status_code=400, detail="system_status 只能是 ACTIVE / DISABLED")

    a = AdAccount(
        id=str(uuid.uuid4()),
        business_id=data.business_id,
        account_id=data.account_id,
        account_name=account_name or data.account_id,
        account_status=data.account_status,
        currency=data.currency,
        timezone=data.timezone,
        system_status=data.system_status,
        daily_spend_limit=data.daily_spend_limit,
        monthly_spend_limit=data.monthly_spend_limit,
        risk_score=data.risk_score,
        capabilities={},
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return account_to_dict(a)


@router.put("/{account_pk}", response_model=dict)
def update_account(
    account_pk: str,
    data: AccountUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新账户信息（管理员）

    变更 business_id 时会先校验账户确实归属目标 BM，校验不通过不生效。
    注意：Meta 侧字段（account_status / effective_status / amount_spent 等）
    由同步写入，不在此接口修改。
    """
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")

    _UNSET = object()  # 区分"未传该字段"与"显式传 null"
    payload = data.model_dump(exclude_unset=True)
    # business_id 单独处理，避免直接 setattr 绕过归属校验
    new_business_id = payload.pop("business_id", _UNSET)
    skip_verification = bool(payload.pop("skip_verification", False))
    if new_business_id is not _UNSET:
        _apply_meta_transfer(db, a, new_business_id, skip_verification=skip_verification)

    for field, value in payload.items():
        if field == "system_status":
            if value not in (s.value for s in SystemStatus):
                raise HTTPException(status_code=400, detail="system_status 只能是 ACTIVE / DISABLED")
            a.system_status_at = datetime.utcnow()
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return account_to_dict(a)


@router.post("/bulk", response_model=dict)
def bulk_update_accounts(
    payload: BulkRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量操作账户（管理员）

    支持 action：
      - freeze   批量冻结（可带 reason）
      - unfreeze 批量解冻
      - delete   批量删除（同时清理用户分配关联）
      - transfer 批量转移 BM 归属（business_id 必填）

    批量操作逐条处理，**单条失败不影响其余条目**，失败明细在 errors 中返回。
    """
    if payload.action not in ("freeze", "unfreeze", "delete", "transfer"):
        raise HTTPException(
            status_code=400, detail="action 只能是 freeze / unfreeze / delete / transfer"
        )
    if not payload.account_ids:
        raise HTTPException(status_code=400, detail="account_ids 不能为空")
    if payload.action == "transfer" and not (payload.business_id or "").strip():
        raise HTTPException(status_code=400, detail="action=transfer 时 business_id 必填")

    success, failed = 0, 0
    errors: List[dict] = []

    for account_pk in payload.account_ids:
        a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
        if not a:
            failed += 1
            errors.append({"account_id": account_pk, "error": "账户不存在"})
            continue

        try:
            if payload.action == "freeze":
                # 系统侧禁用 = 不参与批量投放；Meta 侧状态不受影响
                a.system_status = SystemStatus.DISABLED.value
                a.system_status_reason = payload.reason
                a.system_status_at = datetime.utcnow()
            elif payload.action == "unfreeze":
                a.system_status = SystemStatus.ACTIVE.value
                a.system_status_reason = None
                a.system_status_at = datetime.utcnow()
            elif payload.action == "transfer":
                _apply_meta_transfer(
                    db, a, payload.business_id, skip_verification=payload.skip_verification
                )
            elif payload.action == "delete":
                db.query(UserAccount).filter(
                    UserAccount.account_id == a.id
                ).delete(synchronize_session=False)
                db.delete(a)
            success += 1
        except HTTPException as e:
            failed += 1
            errors.append({"account_id": a.account_id, "error": e.detail})
        except Exception as e:
            failed += 1
            errors.append({"account_id": a.account_id, "error": f"{type(e).__name__}: {e}"})

    db.commit()

    record_audit(
        db,
        action=f"BULK_{payload.action.upper()}_ACCOUNT",
        resource_type="ad_account",
        user_id=current_user.id,
        request_data={
            "action": payload.action,
            "count": len(payload.account_ids),
            "business_id": payload.business_id,
            "skip_verification": payload.skip_verification,
        },
        response_data={"success": success, "failed": failed},
        request=request,
    )
    logger.info(f"[accounts] 批量 {payload.action}: success={success} failed={failed}")

    return {"success": True, "action": payload.action, "success_count": success, "failed_count": failed, "errors": errors}


@router.post("/{account_pk}/transfer", response_model=dict)
def transfer_account(
    account_pk: str,
    payload: TransferRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """转移广告账户的 BM 归属（管理员）

    默认会调用 Meta 校验该账户确实在目标 BM 下，避免误挂到错误的 BM
    （挂错 BM 会导致后续用错 Token 访问该账户）。
    """
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")

    old_business_id = a.business_id
    # business_id 为 None（未传或显式 null）时由 _apply_meta_transfer 返回明确提示
    _apply_meta_transfer(
        db, a, payload.business_id, skip_verification=payload.skip_verification
    )
    db.commit()
    db.refresh(a)

    record_audit(
        db,
        action="TRANSFER_ACCOUNT",
        resource_type="ad_account",
        resource_id=a.id,
        user_id=current_user.id,
        request_data={
            "from_business_id": old_business_id,
            "to_business_id": a.business_id,
            "skip_verification": payload.skip_verification,
        },
        request=request,
    )
    return account_to_dict(a)


@router.post("/{account_pk}/freeze", response_model=dict)
def freeze_account(
    account_pk: str,
    reason: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """禁用账户（管理员）

    系统侧置为 DISABLED，即不参与后续批量投放；Meta 侧状态不受影响。
    """
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    a.system_status = SystemStatus.DISABLED.value
    a.system_status_reason = reason
    a.system_status_at = datetime.utcnow()
    db.commit()
    return account_to_dict(a)


@router.post("/{account_pk}/unfreeze", response_model=dict)
def unfreeze_account(
    account_pk: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """启用账户（管理员）"""
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    a.system_status = SystemStatus.ACTIVE.value
    a.system_status_reason = None
    a.system_status_at = datetime.utcnow()
    db.commit()
    return account_to_dict(a)


@router.post("/{account_pk}/assign", response_model=dict)
def assign_users(
    account_pk: str,
    payload: AssignUsers,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """分配账户给多个用户（管理员，写入 user_accounts 关联表）"""
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    existing = {u.id for u in db.query(User).filter(User.id.in_(payload.user_ids)).all()}
    missing = set(payload.user_ids) - existing
    if missing:
        raise HTTPException(status_code=400, detail=f"以下用户不存在: {', '.join(missing)}")
    for uid in payload.user_ids:
        if not db.query(UserAccount).filter(
            UserAccount.user_id == uid, UserAccount.account_id == a.id
        ).first():
            db.add(UserAccount(id=str(uuid.uuid4()), user_id=uid, account_id=a.id, role="viewer"))
    db.commit()
    count = db.query(UserAccount).filter(UserAccount.account_id == a.id).count()
    return {"success": True, "assigned_count": count}


@router.post("/{account_pk}/unassign", response_model=dict)
def unassign_user(
    account_pk: str,
    payload: AssignUsers,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """从账户移除用户分配（管理员）"""
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    db.query(UserAccount).filter(
        UserAccount.account_id == a.id,
        UserAccount.user_id.in_(payload.user_ids),
    ).delete(synchronize_session=False)
    db.commit()
    return {"success": True}


@router.get("/{account_pk}/users", response_model=List[dict])
def account_users(
    account_pk: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """查看账户已分配的用户列表（管理员）"""
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    rows = db.query(UserAccount, User).join(User, UserAccount.user_id == User.id).filter(
        UserAccount.account_id == a.id
    ).all()
    return [{"user_id": u.id, "username": u.username, "email": u.email, "role": ua.role} for ua, u in rows]


@router.delete("/{account_pk}", response_model=dict)
def delete_account(
    account_pk: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除账户（管理员）"""
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    db.query(UserAccount).filter(UserAccount.account_id == a.id).delete(synchronize_session=False)
    db.delete(a)
    db.commit()
    return {"success": True}


# ==================== 风控相关接口 ====================
#
# 6 个接口基于本地数据库（RiskEvent / CampaignJobItem / MetaSyncLog）计算，
# 不实时调用 Meta API，避免风控页打开时产生额外 API 调用与延迟。
# 真实 Meta 侧的健康/限额数据由同步任务定期写入 AdAccount 字段。


def _get_account_for_user(db: Session, account_pk: str, current_user: User) -> AdAccount:
    """风控接口共用：兼容主键 id 与 act_xxx 两种查询 + 权限校验

    前端 RiskControl 页传的是 account_id（act_xxx），而其它接口用主键 id；
    这里先按主键查，查不到再按 account_id 兜底，保持两类调用都可用。
    """
    a = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not a:
        a = db.query(AdAccount).filter(AdAccount.account_id == account_pk).first()
    if not a:
        raise HTTPException(status_code=404, detail="账户不存在")
    if current_user.role != "admin":
        linked = db.query(UserAccount).filter(
            UserAccount.user_id == current_user.id,
            UserAccount.account_id == a.id,
        ).first()
        if not linked:
            raise HTTPException(status_code=403, detail="无权访问该账户")
    return a


def _risk_event_to_dict(e: RiskEvent) -> dict:
    return {
        "id": e.id,
        "event_type": e.event_type.value if e.event_type else None,
        "risk_level": e.risk_level.value if e.risk_level else None,
        "risk_score": e.risk_score,
        "title": e.title,
        "description": e.description,
        "related_campaign_id": e.related_campaign_id,
        "related_ad_id": e.related_ad_id,
        "is_resolved": e.is_resolved,
        "resolution": e.resolution,
        "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        "auto_action_taken": e.auto_action_taken,
        "requires_manual_review": e.requires_manual_review,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


@router.get("/{account_pk}/account-health-check")
def account_health_check(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """账户健康检查：综合系统状态 / Meta 状态 / 同步异常 / 风险事件给出体检报告"""
    a = _get_account_for_user(db, account_pk, current_user)

    issues = []
    if a.system_status == SystemStatus.DISABLED.value:
        issues.append({"code": "system_disabled", "message": a.system_status_reason or "账户被系统禁用"})
    # Meta 侧状态非 ACTIVE 视为异常
    if a.account_status and str(a.account_status).upper() != "ACTIVE":
        issues.append({"code": "meta_status_abnormal", "message": f"Meta 状态异常: {a.account_status}"})
    if a.disable_reason:
        issues.append({"code": "disable_reason", "message": a.disable_reason})
    if a.last_sync_error:
        issues.append({"code": "sync_error", "message": f"同步异常: {a.last_sync_error}"})

    unresolved_count = (
        db.query(RiskEvent)
        .filter(RiskEvent.ad_account_id == a.id, RiskEvent.is_resolved.is_(False))
        .count()
    )
    if unresolved_count > 0:
        issues.append({"code": "unresolved_risk", "message": f"{unresolved_count} 个未解决风险事件"})

    if a.risk_score is not None and a.risk_score >= 0.7:
        issues.append({"code": "high_risk_score", "message": f"风险评分过高: {a.risk_score:.2f}"})

    is_healthy = len(issues) == 0
    if is_healthy:
        status = "normal"
    elif a.system_status == SystemStatus.DISABLED.value or len(issues) >= 3:
        status = "danger"
    else:
        status = "warning"

    return {
        "is_healthy": is_healthy,
        "health_report": {
            "status": status,
            "issues": issues,
            "risk_score": a.risk_score,
            "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
            "checked_at": datetime.utcnow().isoformat(),
        },
    }


@router.get("/{account_pk}/fraud-score")
def account_fraud_score(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """欺诈评分：基于账户 risk_score 字段 + 未解决的高危风险事件加权（0-1.0）"""
    a = _get_account_for_user(db, account_pk, current_user)
    base = float(a.risk_score or 0.0)

    critical_count = (
        db.query(RiskEvent)
        .filter(
            RiskEvent.ad_account_id == a.id,
            RiskEvent.is_resolved.is_(False),
            RiskEvent.risk_level == RiskLevel.CRITICAL.value,
        )
        .count()
    )
    high_count = (
        db.query(RiskEvent)
        .filter(
            RiskEvent.ad_account_id == a.id,
            RiskEvent.is_resolved.is_(False),
            RiskEvent.risk_level == RiskLevel.HIGH.value,
        )
        .count()
    )
    # 每个未解决 critical +0.1，high +0.05，封顶 1.0
    score = min(1.0, base + critical_count * 0.1 + high_count * 0.05)
    return {"fraud_score": round(score, 4)}


@router.get("/{account_pk}/risk-events")
def account_risk_events(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """风险事件列表：按时间倒序返回该账户的风险事件"""
    a = _get_account_for_user(db, account_pk, current_user)
    events = (
        db.query(RiskEvent)
        .filter(RiskEvent.ad_account_id == a.id)
        .order_by(RiskEvent.created_at.desc())
        .limit(100)
        .all()
    )
    return {"events": [_risk_event_to_dict(e) for e in events]}


@router.get("/{account_pk}/safety-recommendations")
def account_safety_recommendations(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """安全建议：基于健康检查 + 未解决风险事件生成处置建议"""
    a = _get_account_for_user(db, account_pk, current_user)
    actions = []

    if a.system_status == SystemStatus.DISABLED.value:
        actions.append({
            "type": "review_account",
            "priority": "critical",
            "message": "账户被系统禁用，请核查原因后恢复",
            "reason": a.system_status_reason or "未知",
        })
    if a.risk_score is not None and a.risk_score >= 0.7:
        actions.append({
            "type": "reduce_risk",
            "priority": "high",
            "message": "风险评分过高，建议暂停高风险投放并复查素材",
            "reason": f"risk_score={a.risk_score:.2f}",
        })
    if a.last_sync_error:
        actions.append({
            "type": "fix_sync",
            "priority": "medium",
            "message": "同步异常，建议检查 BM 凭据或网络后重新同步",
            "reason": a.last_sync_error,
        })

    unresolved = (
        db.query(RiskEvent)
        .filter(RiskEvent.ad_account_id == a.id, RiskEvent.is_resolved.is_(False))
        .order_by(RiskEvent.created_at.desc())
        .limit(5)
        .all()
    )
    for e in unresolved:
        actions.append({
            "type": e.event_type.value if e.event_type else "risk_event",
            "priority": e.risk_level.value if e.risk_level else "medium",
            "message": e.title,
            "reason": e.description or "",
        })

    return {"recommendations": {"actions": actions}}


@router.get("/{account_pk}/publish-frequency-check")
def account_publish_frequency_check(
    account_pk: str,
    hours: int = Query(24, ge=1, le=168, description="统计时间窗口（小时）"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """发布频次检查：统计该账户 N 小时内 CampaignJobItem 创建数

    用于判断是否短时间批量投放过于频繁（可能触发 Meta 风控）。
    """
    a = _get_account_for_user(db, account_pk, current_user)
    since = datetime.utcnow() - timedelta(hours=hours)
    count = (
        db.query(CampaignJobItem)
        .filter(
            CampaignJobItem.ad_account_id == a.id,
            CampaignJobItem.created_at >= since,
        )
        .count()
    )
    # 阈值：24h 内 >=20 danger，>=10 warning，其余 safe
    # hours 不同时按比例折算
    threshold_warning = max(1, int(10 * hours / 24))
    threshold_danger = max(2, int(20 * hours / 24))
    if count >= threshold_danger:
        status = "danger"
    elif count >= threshold_warning:
        status = "warning"
    else:
        status = "safe"
    return {
        "frequency_report": {
            "frequency_status": status,
            "count": count,
            "hours": hours,
            "threshold_warning": threshold_warning,
            "threshold_danger": threshold_danger,
        }
    }


@router.get("/{account_pk}/rate-limit-status")
def account_rate_limit_status(
    account_pk: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """API 限流状态：基于该账户所属 BM 最近 1 小时的同步日志数估算用量

    说明：Meta Graph API 的真实用量需对接 app-level 调用统计，
    此处以同步日志数近似估算，供前端展示相对水位，非精确值。
    """
    a = _get_account_for_user(db, account_pk, current_user)
    since = datetime.utcnow() - timedelta(hours=1)
    sync_count = (
        db.query(MetaSyncLog)
        .filter(
            MetaSyncLog.business_id == a.business_id,
            MetaSyncLog.created_at >= since,
        )
        .count()
    )
    # 假定每小时 200 次为参考上限（实际因 App 而异）
    limit = 200
    usage_ratio = min(1.0, sync_count / limit) if limit else 0.0
    return {
        "rate_limits": {
            "hour": {
                "usage_ratio": round(usage_ratio, 4),
                "count": sync_count,
                "limit": limit,
            }
        }
    }
