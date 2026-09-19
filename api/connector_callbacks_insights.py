from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from config.settings import settings
from services.request_signer import verify_request
from models.connector_insights import ConnectorInsightsSnapshot
from core.database import get_db
from core.logger import logger
from sqlalchemy.orm import Session
import uuid

router = APIRouter(prefix="/api/v1/internal/fb-connector", tags=["FB Connector 报表回调"])

class InsightsCallback(BaseModel):
    event: str = "insights.completed"
    request_id: str
    credential_id: str
    account_id: str
    days: int = Field(..., ge=1, le=90)
    items: list[dict] = []

@router.post("/insights")
async def insights_callback(request: Request, db: Session = Depends(get_db), x_signature: str | None = Header(None), x_timestamp: str | None = Header(None), x_request_id: str | None = Header(None), x_idempotency_key: str | None = Header(None)):
    body = await request.body()
    headers = {"X-Signature": x_signature or "", "X-Timestamp": x_timestamp or "", "X-Request-Id": x_request_id or "", "X-Idempotency-Key": x_idempotency_key or ""}
    if not settings.SAAS_INTERNAL_SIGNING_KEY or not verify_request(settings.SAAS_INTERNAL_SIGNING_KEY, headers, "POST", "/api/v1/internal/fb-connector/insights", body):
        raise HTTPException(status_code=401, detail="invalid connector signature")
    payload = InsightsCallback.model_validate_json(body)
    logger.info(
        "[ConnectorInsightsCallback] received request_id=%s account_id=%s items=%s",
        payload.request_id,
        payload.account_id,
        len(payload.items),
    )
    old = db.query(ConnectorInsightsSnapshot).filter(ConnectorInsightsSnapshot.request_id == payload.request_id).first()
    if old:
        logger.info("[ConnectorInsightsCallback] duplicate request_id=%s", payload.request_id)
        return {"accepted": True, "duplicate": True, "request_id": payload.request_id}
    db.add(ConnectorInsightsSnapshot(id=uuid.uuid4().hex, request_id=payload.request_id, credential_id=payload.credential_id, account_id=payload.account_id, days=payload.days, items=payload.items))
    db.commit()
    logger.info("[ConnectorInsightsCallback] stored request_id=%s account_id=%s", payload.request_id, payload.account_id)
    return {"accepted": True, "duplicate": False, "account_id": payload.account_id, "count": len(payload.items), "request_id": payload.request_id}
