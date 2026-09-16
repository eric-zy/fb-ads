from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from fb_connector.credential_store import DatabaseCredentialVault
from services.meta import MetaAdsService, MetaClient

router = APIRouter(prefix="/internal/meta/reports", tags=["Meta Reports"])

class InsightsRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    days: int = Field(30, ge=1, le=90)
    level: str = Field("account", pattern="^(account|campaign|adset|ad)$")
    since: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    until: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

@router.post("/insights")
async def insights(payload: InsightsRequest):
    try:
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        params = {"level": payload.level}
        if payload.since and payload.until:
            params["time_range"] = {"since": payload.since, "until": payload.until}
        else:
            params["date_preset"] = f"last_{payload.days}d"
        rows = MetaAdsService(MetaClient(access_token=token)).get_insights(payload.account_id, params)
        return {"account_id": payload.account_id, "days": payload.days, "level": payload.level, "items": rows}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
