from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import uuid
from fb_connector.models import ConnectorDeliveryTask, connector_session_factory

router = APIRouter(prefix="/internal/meta/campaigns", tags=["Meta Delivery"])

class CampaignCreateRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    payload: dict
    idempotency_key: str = Field(..., min_length=8, max_length=128)

class CampaignListRequest(BaseModel):
    account_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)

class CampaignPauseRequest(BaseModel):
    campaign_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    idempotency_key: str = Field(..., min_length=8, max_length=128)

class ObjectRequest(BaseModel):
    object_type: str = Field(..., pattern="^(CAMPAIGN|ADSET|AD)$")
    object_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)
    fields: dict = Field(..., min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)

class ParentRequest(BaseModel):
    parent_id: str = Field(..., min_length=1, max_length=64)
    credential_id: str = Field(..., min_length=1, max_length=50)

class CleanupRequest(BaseModel):
    connector_task_id: str = Field(..., min_length=1, max_length=50)
    credential_id: str = Field(..., min_length=1, max_length=50)

@router.post("/cleanup")
async def cleanup_deployment(payload: CleanupRequest):
    from fb_connector.credential_store import DatabaseCredentialVault
    from services.meta.service import MetaAdsService
    from services.fb_client import MetaClient
    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, payload.connector_task_id)
        if not row:
            raise HTTPException(status_code=404, detail="海外任务不存在")
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        service = MetaAdsService(MetaClient(access_token=token))
        ids = []
        objects = row.objects or {}
        for group in ("ads", "creatives", "adsets"):
            ids.extend([x.get("id") for x in objects.get(group, []) if x.get("id")])
        if row.campaign_id:
            ids.append(row.campaign_id)
        errors = []
        for object_id in ids:
            try:
                service.delete_object(object_id)
            except Exception as exc:
                errors.append({"id": object_id, "error": str(exc)})
        return {"status": "SUCCESS" if not errors else "PARTIAL", "deleted": [x for x in ids if x not in {e["id"] for e in errors}], "errors": errors}
    finally:
        session.close()

@router.post("/deploy", status_code=202)
async def deploy_campaign(payload: dict):
    """完整 Campaign/AdSet/Creative/Ad 协议入口，复用幂等创建任务。"""
    required = ("task_id", "credential_id", "account_id", "idempotency_key", "campaign", "adsets")
    missing = [key for key in required if key not in payload]
    if missing:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"缺少字段: {', '.join(missing)}")
    request = CampaignCreateRequest(task_id=payload["task_id"], credential_id=payload["credential_id"], account_id=payload["account_id"], payload=payload, idempotency_key=payload["idempotency_key"])
    return await create_campaign(request)

def _meta_service(credential_id: str):
    from fb_connector.credential_store import DatabaseCredentialVault
    from services.meta.service import MetaAdsService
    from services.fb_client import MetaClient
    token = DatabaseCredentialVault().get_access_token(credential_id)
    return MetaAdsService(MetaClient(access_token=token))

@router.post("/adsets")
async def list_adsets(payload: ParentRequest):
    return {"parent_id": payload.parent_id, "adsets": _meta_service(payload.credential_id).list_adsets(payload.parent_id)}

@router.post("/ads")
async def list_ads(payload: ParentRequest):
    return {"parent_id": payload.parent_id, "ads": _meta_service(payload.credential_id).list_ads(payload.parent_id)}

@router.post("/update-object")
async def update_object(payload: ObjectRequest):
    service = _meta_service(payload.credential_id)
    fields = payload.fields
    if set(fields) - {"status", "daily_budget"}:
        raise HTTPException(status_code=400, detail="只允许更新 status 或 daily_budget")
    if "status" in fields and fields["status"] not in {"ACTIVE", "PAUSED"}:
        raise HTTPException(status_code=400, detail="status 必须为 ACTIVE 或 PAUSED")
    if "daily_budget" in fields:
        try:
            fields["daily_budget"] = int(fields["daily_budget"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="daily_budget 必须为整数分")
        if fields["daily_budget"] <= 0:
            raise HTTPException(status_code=400, detail="daily_budget 必须为正数")
    if payload.object_type == "CAMPAIGN":
        result = service.update_campaign(payload.object_id, fields)
    elif payload.object_type == "ADSET":
        result = service.update_adset(payload.object_id, fields)
    else:
        if "daily_budget" in fields:
            raise HTTPException(status_code=400, detail="广告不支持更新 daily_budget")
        result = service.update_ad(payload.object_id, fields)
    return {"object_type": payload.object_type, "object_id": payload.object_id, "fields": fields, "result": result, "idempotency_key": payload.idempotency_key}

@router.post("/list")
async def list_campaigns(payload: CampaignListRequest):
    from fb_connector.credential_store import DatabaseCredentialVault
    token = DatabaseCredentialVault().get_access_token(payload.credential_id)
    from services.meta.service import MetaAdsService
    from services.fb_client import MetaClient
    campaigns = MetaAdsService(MetaClient(access_token=token)).list_campaigns(payload.account_id)
    return {"account_id": payload.account_id, "credential_id": payload.credential_id, "campaigns": campaigns}

@router.post("/pause")
async def pause_campaign(payload: CampaignPauseRequest):
    from fb_connector.credential_store import DatabaseCredentialVault
    from services.meta.service import MetaAdsService
    from services.fb_client import MetaClient
    token = DatabaseCredentialVault().get_access_token(payload.credential_id)
    result = MetaAdsService(MetaClient(access_token=token)).pause_campaign(payload.campaign_id)
    return {"campaign_id": payload.campaign_id, "credential_id": payload.credential_id, "result": result, "idempotency_key": payload.idempotency_key}

@router.post("/create", status_code=202)
async def create_campaign(payload: CampaignCreateRequest):
    session = connector_session_factory()
    try:
        old = session.query(ConnectorDeliveryTask).filter(ConnectorDeliveryTask.idempotency_key == payload.idempotency_key).first()
        if old:
            return {"status": old.status, "connector_task_id": old.task_id, "task_id": payload.task_id, "idempotency_key": old.idempotency_key}
        connector_task_id = uuid.uuid4().hex
        session.add(ConnectorDeliveryTask(task_id=connector_task_id, idempotency_key=payload.idempotency_key, status="QUEUED", step="QUEUED")); session.commit()
    finally:
        session.close()
    from fb_connector.tasks import create_campaign_task
    create_campaign_task.delay(connector_task_id, payload.credential_id, payload.account_id, payload.payload, payload.idempotency_key)
    return {"status": "QUEUED", "connector_task_id": connector_task_id, "task_id": payload.task_id, "idempotency_key": payload.idempotency_key}

@router.get("/create/{connector_task_id}")
async def delivery_status(connector_task_id: str):
    session = connector_session_factory()
    try:
        row = session.get(ConnectorDeliveryTask, connector_task_id)
        if not row: return {"status": "NOT_FOUND", "connector_task_id": connector_task_id}
        return {"status": row.status, "step": row.step, "connector_task_id": row.task_id, "campaign_id": row.campaign_id, "objects": row.objects or {}, "error_message": row.error_message}
    finally: session.close()
