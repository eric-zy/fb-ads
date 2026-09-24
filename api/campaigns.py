"""已创建 Meta 投放对象查询与异步控制接口。"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.audit import record_audit
from core.database import get_db
from core.enums import ActionType
from models import AdAccount, AdGroup, Campaign, AdSetInstance, AdInstance, CampaignInstance, CampaignJob, CampaignJobItem, AsyncTaskRecord, DeliveryAction, SyncAlert, User
from services.job_service import JobService
from services.account_access import accessible_account_ids
from tasks.meta_sync_tasks import sync_delivery_objects_task, sync_single_ad_group_task, update_delivery_object_task
from celery_app import celery_app

router = APIRouter(prefix="/api/v1", tags=["Meta 投放对象"])

def _scope(query, model, user):
    """租户用户只能访问本租户对象；平台管理员可跨租户审计。"""
    if getattr(user, "is_platform_admin", lambda: False)() and not getattr(user, "tenant_id", None):
        return query
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="当前账号未绑定租户")
    return query.filter(model.tenant_id == tenant_id)

def _publisher_info(db: Session, user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return {"id": user_id, "username": user.username, "email": user.email} if user else {"id": user_id, "username": "已删除用户", "email": None}


def _require_action_permission(user: User, action: str) -> None:
    required = {
        "PAUSE": "campaign:pause",
        "ENABLE": "campaign:enable",
        "ARCHIVE": "campaign:archive",
        "DELETE": "campaign:delete",
        "RESTORE": "campaign:restore",
        "SYNC": "campaign:sync",
        "UPDATE_BUDGET": "campaign:update_budget",
    }.get(action)
    if user.is_admin() or required in (user.permissions or []):
        return
    # 兼容现有已授予 job:create 的投放操作用户，管理员可在角色页逐步切换到细粒度权限。
    if action in {"PAUSE", "ENABLE"} and "job:create" in (user.permissions or []):
        return
    raise HTTPException(status_code=403, detail=f"没有执行 {action} 操作的权限")


def _visible_accounts(db: Session, user: User) -> Optional[set[str]]:
    return accessible_account_ids(db, user)


def _can_see_account(visible: Optional[set[str]], account_id: str) -> bool:
    return visible is None or account_id in visible


@router.get("/ad-groups/search")
def search_synced_ad_groups(
    account_id: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """搜索当前租户已同步的 Meta 广告组，供发布时复用。

    返回的是本地 canonical 对象及其父 Campaign；客户端只提交本地
    ``ad_group.id``，发布任务再次从数据库解析 Meta ID，避免篡改或串号。
    """
    limit = max(1, min(limit, 100))
    visible = _visible_accounts(db, current_user)
    query = (
        _scope(db.query(AdGroup, Campaign, AdAccount), AdGroup, current_user)
        .join(Campaign, AdGroup.campaign_id == Campaign.id)
        .join(AdAccount, Campaign.ad_account_id == AdAccount.id)
        .filter(Campaign.tenant_id == AdGroup.tenant_id)
    )
    if visible is not None:
        query = query.filter(Campaign.ad_account_id.in_(visible or {"__no_accounts__"}))
    if account_id:
        if visible is not None and account_id not in visible:
            return []
        query = query.filter(Campaign.ad_account_id == account_id)
    if status:
        query = query.filter(AdGroup.status == status.upper())
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            (AdGroup.name.ilike(pattern))
            | (AdGroup.ad_group_id.ilike(pattern))
            | (Campaign.name.ilike(pattern))
            | (Campaign.campaign_id.ilike(pattern))
        )
    rows = query.order_by(AdGroup.updated_at.desc().nullslast(), AdGroup.created_at.desc()).limit(limit).all()
    stale_before = datetime.utcnow() - timedelta(hours=24)
    return [
        {
            "id": group.id,
            "ad_group_id": group.ad_group_id,
            "name": group.name,
            "status": str(group.status or "ACTIVE"),
            "ad_account_id": campaign.ad_account_id,
            "account_name": account.account_name,
            "campaign": {
                "id": campaign.id,
                "campaign_id": campaign.campaign_id,
                "name": campaign.name,
            "status": str(getattr(campaign.status, "value", campaign.status) or "ACTIVE"),
            },
            "updated_at": group.updated_at.isoformat() if group.updated_at else None,
            # 没有更新时间也视为过期：这类记录可能只完成了本地落库，
            # 不能直接作为发布时的最新 Meta 配置使用。
            "stale": not group.updated_at or group.updated_at < stale_before,
        }
        for group, campaign, account in rows
    ]

@router.post("/ad-groups/{ad_group_id}/sync")
def sync_synced_ad_group(
    ad_group_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """刷新一个已同步广告组及其账户下的完整投放对象树。

    广告组搜索返回的是 canonical AdGroup ID，而现有批量同步接口接收
    CampaignInstance/AdSetInstance ID；单独提供此接口，避免前端把两类 ID
    混用，也让发布页可以直接发起“立即同步”。
    """
    _require_action_permission(current_user, "SYNC")
    visible = _visible_accounts(db, current_user)
    row = (
        _scope(db.query(AdGroup), AdGroup, current_user)
        .join(Campaign, AdGroup.campaign_id == Campaign.id)
        .filter(AdGroup.id == ad_group_id, Campaign.tenant_id == AdGroup.tenant_id)
        .first()
    )
    if not row or not _can_see_account(visible, row.campaign.ad_account_id):
        raise HTTPException(status_code=404, detail="广告组不存在或无权同步")

    account_id = row.campaign.ad_account_id
    task = sync_single_ad_group_task.delay(ad_group_id, account_id)
    db.add(AsyncTaskRecord(
        task_id=task.id,
        task_type="META_SYNC",
        object_type="ADSET",
        object_ids=[ad_group_id],
        created_by=current_user.id,
    ))
    db.commit()
    record_audit(
        db,
        action="SYNC_DELIVERY_OBJECTS",
        resource_type="ad_group",
        resource_id=ad_group_id,
        user_id=current_user.id,
        request_data={"ad_group_id": ad_group_id, "account_id": account_id},
        response_data={"status": "QUEUED", "task_id": task.id},
    )
    return {
        "status": "QUEUED",
        "task_id": task.id,
        "ad_group_id": ad_group_id,
        "account_id": account_id,
    }

@router.get("/sync-alerts")
def list_sync_alerts(limit: int = 50, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    limit = max(1, min(limit, 200))
    query = _scope(db.query(SyncAlert), SyncAlert, current_user).filter(SyncAlert.is_resolved.is_(False))
    visible = _visible_accounts(db, current_user)
    if visible is not None:
        query = query.filter(SyncAlert.ad_account_id.in_(visible or {"__no_accounts__"}))
    return [row.to_dict() for row in query.order_by(SyncAlert.created_at.desc()).limit(limit).all()]

@router.post("/sync-alerts/{alert_id}/resolve")
def resolve_sync_alert(alert_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    alert = _scope(db.query(SyncAlert), SyncAlert, current_user).filter(SyncAlert.id == alert_id, SyncAlert.is_resolved.is_(False)).first()
    visible = _visible_accounts(db, current_user)
    if not alert or (visible is not None and alert.ad_account_id not in visible):
        raise HTTPException(status_code=404, detail="告警不存在或已处理")
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return alert.to_dict()

@router.get("/tasks")
def list_async_task_records(limit: int = 50, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    limit = max(1, min(limit, 200))
    query = _scope(db.query(AsyncTaskRecord), AsyncTaskRecord, current_user)
    if not current_user.is_admin():
        query = query.filter(AsyncTaskRecord.created_by == current_user.id)
    return [row.to_dict() for row in query.order_by(AsyncTaskRecord.created_at.desc()).limit(limit).all()]

@router.get("/tasks/{task_id}")
def get_async_task_status(task_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    """查询 Meta 同步/启停 Celery 任务状态。"""
    if len(task_id) > 100 or any(ch not in "0123456789abcdefABCDEF-" for ch in task_id):
        raise HTTPException(status_code=400, detail="任务 ID 格式错误")
    record = _scope(db.query(AsyncTaskRecord), AsyncTaskRecord, current_user).filter(AsyncTaskRecord.task_id == task_id).first()
    if not record or (not current_user.is_admin() and record.created_by != current_user.id):
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    result = celery_app.AsyncResult(task_id)
    payload = {"task_id": task_id, "state": result.state}
    if result.successful():
        # 不直接回传任务结果，避免将账户标识、Meta 响应等内部数据暴露到前端。
        value = result.result if isinstance(result.result, dict) else {}
        payload["result"] = {
            "status": value.get("status", "success"),
            "error_count": value.get("error_count", 0),
        }
        # 单个广告组同步需要让发布页确认刷新的是当前选中对象；
        # 这里只返回本地 canonical ID 和时间，不暴露 Meta 原始响应或凭据。
        if value.get("ad_group_id"):
            payload["result"]["ad_group_id"] = str(value["ad_group_id"])
        if value.get("updated_at"):
            payload["result"]["updated_at"] = value["updated_at"]
        if str(value.get("status", "")).lower() == "failed":
            payload["error"] = str(value.get("error") or "Meta 同步任务失败")
    elif result.failed():
        payload["error"] = str(result.result)
    record.status = result.state
    if payload.get("result"):
        record.result_summary = payload["result"]
    if result.ready():
        record.finished_at = datetime.utcnow()
    db.commit()
    return payload

class CampaignActionRequest(BaseModel):
    action: str
    ids: List[str] = []
    object_type: Optional[str] = None
    ad_account_ids: Optional[List[str]] = None
    budget: Optional[float] = None
    idempotency_key: Optional[str] = None


@router.get("/delivery-actions")
def list_delivery_actions(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """查看当前用户可见账户的启停/归档操作记录。"""
    limit = max(1, min(limit, 200))
    visible = _visible_accounts(db, current_user)
    query = _scope(db.query(DeliveryAction), DeliveryAction, current_user)
    if visible is not None:
        query = query.filter(DeliveryAction.account_id.in_(visible or {"__no_accounts__"}))
    if status:
        query = query.filter(DeliveryAction.status == status.upper())
    return [row.to_dict() for row in query.order_by(DeliveryAction.created_at.desc()).limit(limit).all()]


@router.get("/delivery-actions/{action_id}")
def get_delivery_action(action_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    visible = _visible_accounts(db, current_user)
    query = _scope(db.query(DeliveryAction), DeliveryAction, current_user).filter(DeliveryAction.id == action_id)
    row = query.first()
    if not row or not _can_see_account(visible, row.account_id):
        raise HTTPException(status_code=404, detail="操作记录不存在或无权访问")
    return row.to_dict()


@router.post("/delivery-actions/{action_id}/retry")
def retry_delivery_action(action_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    """仅重试失败的 AdSet/Ad 状态操作，创建新的动作记录避免覆盖原始失败证据。"""
    visible = _visible_accounts(db, current_user)
    row = _scope(db.query(DeliveryAction), DeliveryAction, current_user).filter(DeliveryAction.id == action_id).first()
    if not row or not _can_see_account(visible, row.account_id):
        raise HTTPException(status_code=404, detail="操作记录不存在或无权访问")
    if row.status != "FAILED":
        raise HTTPException(status_code=409, detail="只有失败的操作可以重试")
    _require_action_permission(current_user, row.action)
    if row.object_type == "ADSET":
        target = _scope(db.query(AdSetInstance), AdSetInstance, current_user).filter(AdSetInstance.id == row.object_id).first()
        meta_id = target.meta_adset_id if target else None
    elif row.object_type == "AD":
        target = _scope(db.query(AdInstance), AdInstance, current_user).filter(AdInstance.id == row.object_id).first()
        meta_id = target.meta_ad_id if target else None
    else:
        raise HTTPException(status_code=400, detail="Campaign 操作请从投放任务中重试")
    if not target or not meta_id:
        raise HTTPException(status_code=409, detail="本地对象或 Meta ID 不存在，无法重试")
    target_account_id = (
        target.campaign_instance.ad_account_id
        if row.object_type == "ADSET"
        else target.adset_instance.campaign_instance.ad_account_id
    )
    if target_account_id != row.account_id:
        raise HTTPException(status_code=409, detail="操作记录与对象账户不一致，拒绝重试")
    desired_status = (
        "DELETED" if row.action == "DELETE" else
        "ARCHIVED" if row.action == "ARCHIVE" else
        "ACTIVE" if row.action == "ENABLE" else "PAUSED"
    )
    retry_row = DeliveryAction(
        id=uuid.uuid4().hex,
        object_type=row.object_type,
        object_id=row.object_id,
        account_id=row.account_id,
        action=row.action,
        requested_by=current_user.id,
        before_status=getattr(target, "status", None),
        desired_status=desired_status,
        idempotency_key=f"retry:{row.id}:{uuid.uuid4().hex}",
        request_payload={"retry_of": row.id},
    )
    db.add(retry_row)
    db.commit()
    task = update_delivery_object_task.delay(row.object_type, row.object_id, row.account_id, row.action, retry_row.id)
    retry_row.task_id = task.id
    retry_row.status = "RUNNING"
    db.add(AsyncTaskRecord(task_id=task.id, task_type="META_STATUS_UPDATE", object_type=row.object_type, object_ids=[row.object_id], created_by=current_user.id))
    db.commit()
    record_audit(
        db,
        action="RETRY_DELIVERY_ACTION",
        resource_type="delivery_action",
        resource_id=retry_row.id,
        user_id=current_user.id,
        request_data={"retry_of": row.id, "action": row.action, "object_id": row.object_id},
        response_data={"status": "QUEUED", "task_id": task.id},
    )
    return {"status": "QUEUED", "action_id": retry_row.id, "task_id": task.id, "retry_of": row.id}

@router.get("/campaigns")
def list_campaigns(
    ad_account_id: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    visible = _visible_accounts(db, current_user)
    query = _scope(db.query(CampaignInstance), CampaignInstance, current_user)
    if visible is not None:
        query = query.filter(CampaignInstance.ad_account_id.in_(visible or {"__no_accounts__"}))
    if ad_account_id:
        query = query.filter(CampaignInstance.ad_account_id == ad_account_id)
    if status:
        query = query.filter(CampaignInstance.status == status.upper())
    else:
        # 删除是可恢复的业务状态，默认从发布列表隐藏；审计/恢复场景通过 status=DELETED 查询。
        query = query.filter(CampaignInstance.status != "DELETED")
    if keyword and keyword.strip():
        value = f"%{keyword.strip()}%"
        query = query.filter(
            (CampaignInstance.name.ilike(value))
            | (CampaignInstance.meta_campaign_id.ilike(value))
        )
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    # CampaignInstance 是账户级对象，同一模板发布到多个账户会有多条记录。
    # 列表按“模板 + 名称”合并为一个逻辑广告系列，但保留全部实例 ID，
    # 这样展示不重复，批量操作仍可准确作用于每个广告账户。
    rows = query.order_by(CampaignInstance.created_at.desc()).all()
    grouped = {}
    for row in rows:
        key = (row.template_id, row.name or "")
        grouped.setdefault(key, []).append(row)
    groups = list(grouped.values())
    total = len(groups)
    groups = groups[(page - 1) * page_size: page * page_size]
    result = []
    for group in groups:
        row = group[0]
        payload = row.to_dict()
        payload["grouped"] = len(group) > 1
        payload["grouped_ids"] = [item.id for item in group]
        payload["account_count"] = len(group)
        payload["grouped_accounts"] = [
            {
                "id": item.ad_account_id,
                "name": item.ad_account.account_name if item.ad_account else item.ad_account_id,
                "meta_campaign_id": item.meta_campaign_id,
                "status": item.status,
                "meta_status": item.meta_status,
            }
            for item in group
        ]
        if len(group) > 1:
            payload["account_name"] = "、".join(dict.fromkeys(
                item.ad_account.account_name if item.ad_account else item.ad_account_id
                for item in group
            ))
            payload["meta_campaign_ids"] = [item.meta_campaign_id for item in group if item.meta_campaign_id]
            payload["meta_campaign_id"] = f"{len(group)} 个账户"
        publisher = None
        for job in reversed(row.template.jobs if row.template else []):
            item = next((item for item in job.items if item.campaign_instance_id == row.id), None)
            if item:
                publisher = _publisher_info(db, job.created_by)
                break
        payload["publisher"] = publisher
        result.append(payload)
    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.get("/delivery-objects/{object_type}/{object_id}")
def delivery_object_detail(
    object_type: str,
    object_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """返回 Campaign、AdSet 或 Ad 的统一详情、层级关系及最近操作结果。"""
    object_type = object_type.upper()
    visible = _visible_accounts(db, current_user)
    target = None
    account_id = None
    ancestors = {}
    children = []

    if object_type == "CAMPAIGN":
        target = _scope(db.query(CampaignInstance), CampaignInstance, current_user).filter(CampaignInstance.id == object_id).first()
        if target:
            account_id = target.ad_account_id
            children = [
                {**adset.to_dict(), "ads": [ad.to_dict() for ad in adset.ads]}
                for adset in target.adsets
            ]
    elif object_type == "ADSET":
        target = _scope(db.query(AdSetInstance), AdSetInstance, current_user).filter(AdSetInstance.id == object_id).first()
        if target:
            campaign = target.campaign_instance
            account_id = campaign.ad_account_id
            ancestors = {"campaign": campaign.to_dict()}
            children = [ad.to_dict() for ad in target.ads]
    elif object_type == "AD":
        target = _scope(db.query(AdInstance), AdInstance, current_user).filter(AdInstance.id == object_id).first()
        if target:
            adset = target.adset_instance
            campaign = adset.campaign_instance
            account_id = campaign.ad_account_id
            ancestors = {"campaign": campaign.to_dict(), "adset": adset.to_dict()}
    else:
        raise HTTPException(status_code=400, detail="不支持的投放对象类型")

    if not target or not _can_see_account(visible, account_id):
        raise HTTPException(status_code=404, detail="投放对象不存在或无权访问")

    account = target.ad_account if object_type == "CAMPAIGN" else target.campaign_instance.ad_account if object_type == "ADSET" else target.adset_instance.campaign_instance.ad_account
    actions = (
        _scope(db.query(DeliveryAction), DeliveryAction, current_user)
        .filter(DeliveryAction.object_type == object_type, DeliveryAction.object_id == object_id)
        .order_by(DeliveryAction.created_at.desc())
        .limit(30)
        .all()
    )
    return {
        "object_type": object_type,
        "object": target.to_dict(),
        "account": {
            "id": account.id,
            "account_id": account.account_id,
            "account_name": account.account_name,
            "business_id": account.business_id,
            "system_status": account.system_status,
            "account_status": account.account_status,
        } if account else None,
        "ancestors": ancestors,
        "children": children,
        "recent_actions": [row.to_dict() for row in actions],
    }

@router.get("/campaigns/{campaign_id}/adsets")
def list_adsets(
    campaign_id: str,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    campaign = _scope(db.query(CampaignInstance), CampaignInstance, current_user).filter(CampaignInstance.id == campaign_id).first()
    visible = _visible_accounts(db, current_user)
    if not campaign or not _can_see_account(visible, campaign.ad_account_id):
        raise HTTPException(status_code=404, detail="广告系列不存在")
    query = _scope(db.query(AdSetInstance), AdSetInstance, current_user).filter(
        AdSetInstance.campaign_instance_id == campaign_id
    )
    if status:
        query = query.filter(AdSetInstance.status == status.upper())
    else:
        query = query.filter(AdSetInstance.status != "DELETED")
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = query.count()
    rows = (
        query.order_by(AdSetInstance.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [row.to_dict() for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@router.get("/campaigns/{campaign_id}/detail")
def campaign_detail(campaign_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_active_user)):
    """返回本地发布记录的完整层级与投放配置，供投放管理详情页查看。"""
    campaign = _scope(db.query(CampaignInstance), CampaignInstance, current_user).filter(CampaignInstance.id == campaign_id).first()
    visible = _visible_accounts(db, current_user)
    if not campaign or not _can_see_account(visible, campaign.ad_account_id):
        raise HTTPException(status_code=404, detail="广告系列不存在")
    template = campaign.template
    job_item = None
    if template:
        for job in reversed(template.jobs or []):
            item = next((row for row in job.items if row.ad_account_id == campaign.ad_account_id), None)
            if item:
                job_item = item.to_dict()
                job_item["publisher"] = _publisher_info(db, job.created_by)
                break
    recent_jobs = (
        db.query(CampaignJob, CampaignJobItem)
        .join(CampaignJobItem, CampaignJobItem.job_id == CampaignJob.id)
        .filter(
            CampaignJob.tenant_id == campaign.tenant_id,
            CampaignJob.template_id == campaign.template_id,
            CampaignJobItem.ad_account_id == campaign.ad_account_id,
        )
        .order_by(CampaignJob.created_at.desc())
        .limit(30)
        .all()
    )
    recent_actions = []
    for job, item in recent_jobs:
        connector_status = (item.response_payload or {}).get("connector_status") or {}
        recent_actions.append({
            "job_id": job.id,
            "job_item_id": item.id,
            "action": job.action_type,
            "status": item.status,
            "remote_status": connector_status.get("status") or campaign.meta_status,
            "error_code": item.error_code,
            "error_message": item.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        })
    return {
        "campaign": campaign.to_dict(),
        "account": {
            "id": campaign.ad_account.id,
            "account_id": campaign.ad_account.account_id,
            "account_name": campaign.ad_account.account_name,
            "business_id": campaign.ad_account.business_id,
            "system_status": campaign.ad_account.system_status,
            "account_status": campaign.ad_account.account_status,
        } if campaign.ad_account else None,
        "template": template.to_dict() if template else None,
        "creative_config": (template.creative_config_json if template else None),
        "adsets": [
            {
                **adset.to_dict(),
                "ads": [ad.to_dict() for ad in adset.ads],
            }
            for adset in campaign.adsets
        ],
        "job_item": job_item,
        "publisher": job_item.get("publisher") if job_item else None,
        "recent_actions": recent_actions,
    }

@router.get("/adsets/{adset_id}/ads")
def list_ads(
    adset_id: str,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    adset = _scope(db.query(AdSetInstance), AdSetInstance, current_user).filter(AdSetInstance.id == adset_id).first()
    visible = _visible_accounts(db, current_user)
    if not adset or not _can_see_account(visible, adset.campaign_instance.ad_account_id):
        raise HTTPException(status_code=404, detail="广告组不存在")
    query = _scope(db.query(AdInstance), AdInstance, current_user).filter(
        AdInstance.adset_instance_id == adset_id
    )
    if status:
        query = query.filter(AdInstance.status == status.upper())
    else:
        query = query.filter(AdInstance.status != "DELETED")
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total = query.count()
    rows = (
        query.order_by(AdInstance.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [row.to_dict() for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@router.post("/campaigns/actions")
def campaign_action(
    req: CampaignActionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    action = req.action.upper()
    _require_action_permission(current_user, action)
    action_map = {
        "PAUSE": ActionType.PAUSE,
        "ENABLE": ActionType.ENABLE,
        "ARCHIVE": ActionType.ARCHIVE,
        "DELETE": ActionType.DELETE,
        "RESTORE": ActionType.RESTORE,
        "UPDATE_BUDGET": ActionType.UPDATE_BUDGET,
    }
    visible = _visible_accounts(db, current_user)
    if action == "SYNC":
        object_type = (req.object_type or "CAMPAIGN").upper()
        model = {"CAMPAIGN": CampaignInstance, "ADSET": AdSetInstance, "AD": AdInstance}.get(object_type)
        if not model:
            raise HTTPException(status_code=400, detail="不支持的同步对象类型")
        rows = _scope(db.query(model), model, current_user).filter(model.id.in_(req.ids)).all()
        if object_type == "CAMPAIGN":
            visible_rows = [row for row in rows if _can_see_account(visible, row.ad_account_id)]
            account_ids = [row.ad_account_id for row in visible_rows]
        elif object_type == "ADSET":
            visible_rows = [row for row in rows if _can_see_account(visible, row.campaign_instance.ad_account_id)]
            account_ids = [row.campaign_instance.ad_account_id for row in visible_rows]
        else:
            visible_rows = [row for row in rows if _can_see_account(visible, row.adset_instance.campaign_instance.ad_account_id)]
            account_ids = [row.adset_instance.campaign_instance.ad_account_id for row in visible_rows]
        account_ids = sorted(set(account_ids))
        if not account_ids:
            raise HTTPException(status_code=404, detail="未找到可同步的投放对象")
        object_ids = [row.id for row in visible_rows]
        tasks = [sync_delivery_objects_task.delay(account_id) for account_id in account_ids]
        for task in tasks:
            db.add(AsyncTaskRecord(task_id=task.id, task_type="META_SYNC", object_type=object_type, object_ids=object_ids, created_by=current_user.id))
        db.commit()
        record_audit(
            db,
            action="SYNC_DELIVERY_OBJECTS",
            resource_type=object_type.lower(),
            resource_id=object_ids[0] if object_ids else None,
            user_id=current_user.id,
            request_data={"object_type": object_type, "object_ids": object_ids, "account_ids": account_ids},
            response_data={"status": "QUEUED", "task_ids": [task.id for task in tasks]},
        )
        return {"status": "QUEUED", "task_ids": [task.id for task in tasks], "account_ids": account_ids, "object_type": object_type, "object_ids": object_ids}
    action_type = action_map.get(action)
    if not action_type:
        raise HTTPException(status_code=400, detail="不支持的操作")

    instances = _scope(db.query(CampaignInstance), CampaignInstance, current_user).filter(CampaignInstance.id.in_(req.ids)).all()
    instances = [row for row in instances if _can_see_account(visible, row.ad_account_id)]
    if action == "RESTORE" and instances:
        invalid = [row.id for row in instances if row.status not in {"ARCHIVED", "DELETED"}]
        if invalid:
            raise HTTPException(status_code=409, detail="只有已归档或已移除的广告系列可以恢复")
    if not instances and action in ("PAUSE", "ENABLE", "ARCHIVE", "DELETE", "RESTORE"):
        adsets = _scope(db.query(AdSetInstance), AdSetInstance, current_user).filter(AdSetInstance.id.in_(req.ids)).all()
        ads = _scope(db.query(AdInstance), AdInstance, current_user).filter(AdInstance.id.in_(req.ids)).all()
        targets = [{"type": "ADSET", "id": row.id, "account_id": row.campaign_instance.ad_account_id} for row in adsets if _can_see_account(visible, row.campaign_instance.ad_account_id)]
        targets += [{"type": "AD", "id": row.id, "account_id": row.adset_instance.campaign_instance.ad_account_id} for row in ads if _can_see_account(visible, row.adset_instance.campaign_instance.ad_account_id)]
        if targets:
            actions = []
            request_key = req.idempotency_key or uuid.uuid4().hex
            for target in targets:
                row = db.query(AdSetInstance).filter(AdSetInstance.id == target["id"]).first() if target["type"] == "ADSET" else db.query(AdInstance).filter(AdInstance.id == target["id"]).first()
                if action == "RESTORE" and row.status not in {"ARCHIVED", "DELETED"}:
                    raise HTTPException(status_code=409, detail="只有已归档或已移除的对象可以恢复")
                action_key = f"{request_key}:{target['type']}:{target['id']}"
                existing = db.query(DeliveryAction).filter(DeliveryAction.idempotency_key == action_key).first()
                if existing:
                    actions.append(existing)
                    continue
                action_row = DeliveryAction(
                    id=uuid.uuid4().hex,
                    object_type=target["type"],
                    object_id=target["id"],
                    account_id=target["account_id"],
                    action=action,
                    requested_by=current_user.id,
                    before_status=getattr(row, "status", None),
                    desired_status=(
                        "DELETED" if action == "DELETE" else
                        "ARCHIVED" if action == "ARCHIVE" else
                        "PAUSED" if action in {"PAUSE", "RESTORE"} else "ACTIVE"
                    ),
                    idempotency_key=action_key,
                )
                db.add(action_row)
                actions.append(action_row)
            db.commit()
            tasks = []
            for target, action_row in zip(targets, actions):
                if action_row.task_id:
                    continue
                tasks.append((target, action_row, update_delivery_object_task.delay(target["type"], target["id"], target["account_id"], action, action_row.id)))
            for target, action_row, task in tasks:
                action_row.task_id = task.id
                action_row.status = "RUNNING"
                db.add(AsyncTaskRecord(task_id=task.id, task_type="META_STATUS_UPDATE", object_type=target["type"], object_ids=[target["id"]], created_by=current_user.id))
            db.commit()
            record_audit(
                db,
                action=f"{action}_DELIVERY_OBJECTS",
                resource_type="delivery_action",
                resource_id=actions[0].id if actions else None,
                user_id=current_user.id,
                request_data={"action": action, "object_ids": [row.id for row in actions]},
                response_data={"status": "QUEUED", "task_ids": [task.id for _, _, task in tasks]},
            )
            return {"status": "QUEUED", "task_ids": [task.id for _, _, task in tasks], "action_ids": [row.id for row in actions], "object_count": len(actions)}
    if not instances:
        raise HTTPException(status_code=404, detail="未找到可操作的广告系列")
    grouped = defaultdict(list)
    for instance in instances:
        grouped[instance.template_id].append(instance.ad_account_id)

    jobs = []
    for template_id, account_ids in grouped.items():
        params = {"budget_override": req.budget} if action_type == ActionType.UPDATE_BUDGET else {}
        if req.idempotency_key:
            params["_idempotency_key"] = f"{req.idempotency_key}:{template_id}"
        jobs.append(JobService(db).create_job(
            template_id=template_id,
            ad_account_ids=account_ids,
            action_type=action_type,
            params=params,
            created_by=current_user.id,
        ))
    record_audit(
        db,
        action=f"{action}_CAMPAIGNS",
        resource_type="campaign_job",
        resource_id=jobs[0].id if jobs else None,
        user_id=current_user.id,
        request_data={"action": action, "campaign_ids": [row.id for row in instances]},
        response_data={"status": jobs[0].status if jobs else "EMPTY", "job_ids": [job.id for job in jobs]},
    )
    return {"job_id": jobs[0].id, "job_ids": [job.id for job in jobs], "status": jobs[0].status}
