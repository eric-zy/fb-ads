from fastapi import APIRouter
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
        return {"status": row.status, "step": row.step, "connector_task_id": row.task_id, "campaign_id": row.campaign_id, "error_message": row.error_message}
    finally: session.close()
