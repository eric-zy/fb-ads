"""已创建 Meta 投放对象查询与异步控制接口。"""
from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_active_user
from core.database import get_db
from core.enums import ActionType
from models import AdSetInstance, AdInstance, CampaignInstance, AsyncTaskRecord
from services.job_service import JobService
from tasks.meta_sync_tasks import sync_delivery_objects_task, update_delivery_object_task
from celery_app import celery_app

router = APIRouter(prefix="/api/v1", tags=["Meta 投放对象"])

@router.get("/tasks")
def list_async_task_records(limit: int = 50, db: Session = Depends(get_db), _=Depends(get_current_active_user)):
    limit = max(1, min(limit, 200))
    return [row.to_dict() for row in db.query(AsyncTaskRecord).order_by(AsyncTaskRecord.created_at.desc()).limit(limit).all()]

@router.get("/tasks/{task_id}")
def get_async_task_status(task_id: str, db: Session = Depends(get_db), _=Depends(get_current_active_user)):
    """查询 Meta 同步/启停 Celery 任务状态。"""
    if len(task_id) > 100 or any(ch not in "0123456789abcdefABCDEF-" for ch in task_id):
        raise HTTPException(status_code=400, detail="任务 ID 格式错误")
    record = db.query(AsyncTaskRecord).filter(AsyncTaskRecord.task_id == task_id).first()
    if not record:
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
    ad_account_ids: Optional[List[str]] = None
    budget: Optional[float] = None

@router.get("/campaigns")
def list_campaigns(
    ad_account_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_active_user),
):
    query = db.query(CampaignInstance)
    if ad_account_id:
        query = query.filter(CampaignInstance.ad_account_id == ad_account_id)
    return [row.to_dict() for row in query.order_by(CampaignInstance.created_at.desc()).all()]

@router.get("/campaigns/{campaign_id}/adsets")
def list_adsets(campaign_id: str, db: Session = Depends(get_db), _=Depends(get_current_active_user)):
    campaign = db.query(CampaignInstance).filter(CampaignInstance.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="广告系列不存在")
    return [row.to_dict() for row in campaign.adsets]

@router.get("/adsets/{adset_id}/ads")
def list_ads(adset_id: str, db: Session = Depends(get_db), _=Depends(get_current_active_user)):
    adset = db.query(AdSetInstance).filter(AdSetInstance.id == adset_id).first()
    if not adset:
        raise HTTPException(status_code=404, detail="广告组不存在")
    return [row.to_dict() for row in adset.ads]

@router.post("/campaigns/actions")
def campaign_action(
    req: CampaignActionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    action_map = {"PAUSE": ActionType.PAUSE, "ENABLE": ActionType.ENABLE, "UPDATE_BUDGET": ActionType.UPDATE_BUDGET}
    if req.action == "SYNC":
        instances = db.query(CampaignInstance).filter(CampaignInstance.id.in_(req.ids)).all()
        if not instances:
            raise HTTPException(status_code=404, detail="未找到可同步的广告系列")
        account_ids = sorted({row.ad_account_id for row in instances})
        tasks = [sync_delivery_objects_task.delay(account_id) for account_id in account_ids]
        for task in tasks:
            db.add(AsyncTaskRecord(task_id=task.id, task_type="META_SYNC", object_type="ACCOUNT", object_ids=account_ids, created_by=current_user.id))
        db.commit()
        return {"status": "QUEUED", "task_ids": [task.id for task in tasks], "account_ids": account_ids}
    action = action_map.get(req.action)
    if not action:
        raise HTTPException(status_code=400, detail="不支持的操作")

    instances = db.query(CampaignInstance).filter(CampaignInstance.id.in_(req.ids)).all()
    if not instances and req.action in ("PAUSE", "ENABLE"):
        adsets = db.query(AdSetInstance).filter(AdSetInstance.id.in_(req.ids)).all()
        ads = db.query(AdInstance).filter(AdInstance.id.in_(req.ids)).all()
        targets = [{"type": "ADSET", "id": row.id, "account_id": row.campaign_instance.ad_account_id} for row in adsets]
        targets += [{"type": "AD", "id": row.id, "account_id": row.adset_instance.campaign_instance.ad_account_id} for row in ads]
        if targets:
            tasks = [update_delivery_object_task.delay(t["type"], t["id"], t["account_id"], req.action) for t in targets]
            for task, target in zip(tasks, targets):
                db.add(AsyncTaskRecord(task_id=task.id, task_type="META_STATUS_UPDATE", object_type=target["type"], object_ids=[target["id"]], created_by=current_user.id))
            db.commit()
            return {"status": "QUEUED", "task_ids": [task.id for task in tasks], "object_count": len(tasks)}
    if not instances:
        raise HTTPException(status_code=404, detail="未找到可操作的广告系列")
    grouped = defaultdict(list)
    for instance in instances:
        grouped[instance.template_id].append(instance.ad_account_id)

    jobs = []
    for template_id, account_ids in grouped.items():
        params = {"budget_override": req.budget} if action == ActionType.UPDATE_BUDGET else {}
        jobs.append(JobService(db).create_job(
            template_id=template_id,
            ad_account_ids=account_ids,
            action_type=action,
            params=params,
            created_by=current_user.id,
        ))
    return {"job_id": jobs[0].id, "job_ids": [job.id for job in jobs], "status": jobs[0].status}
