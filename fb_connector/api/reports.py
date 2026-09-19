from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from fb_connector.credential_store import DatabaseCredentialVault, report_meta_auth_failure
from services.meta import MetaAdsService, MetaClient
from core.logger import logger

router = APIRouter(prefix="/internal/meta/reports", tags=["Meta Reports"])

class InsightsRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)
    account_id: str = Field(..., min_length=1, max_length=64)
    days: int = Field(30, ge=1, le=90)
    level: Literal["account", "campaign", "adset", "ad"] = "account"
    since: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    until: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("credential_id", "account_id", mode="before")
    @classmethod
    def normalize_ids(cls, value):
        # Meta account IDs occasionally come from JSON as numbers.  Keep the
        # wire contract string-based while accepting that harmless variation.
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return str(value).strip()
        return value

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, value):
        # Older callers used Meta's human-readable spelling.  Normalize it at
        # the boundary so all downstream code uses one canonical value.
        aliases = {"ad_set": "adset", "ad-set": "adset", "ads": "ad"}
        if isinstance(value, str):
            return aliases.get(value.strip().lower(), value.strip().lower())
        return value

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.since and self.until:
            try:
                if date.fromisoformat(self.since) > date.fromisoformat(self.until):
                    raise ValueError("since 不能晚于 until")
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
        return self

@router.post("/insights")
async def insights(payload: InsightsRequest):
    logger.info(
        "[ConnectorInsightsAPI] start account_id=%s credential_id=%s days=%s level=%s",
        payload.account_id,
        payload.credential_id,
        payload.days,
        payload.level,
    )
    try:
        token = DatabaseCredentialVault().get_access_token(payload.credential_id)
        params = {"level": payload.level}
        if payload.since and payload.until:
            params["time_range"] = {"since": payload.since, "until": payload.until}
        else:
            params["date_preset"] = f"last_{payload.days}d"
        rows = MetaAdsService(MetaClient(access_token=token)).get_insights(payload.account_id, params)
        logger.info("[ConnectorInsightsAPI] success account_id=%s rows=%s", payload.account_id, len(rows))
        return {"account_id": payload.account_id, "days": payload.days, "level": payload.level, "items": rows}
    except KeyError as exc:
        logger.warning("[ConnectorInsightsAPI] credential failed credential_id=%s error=%s", payload.credential_id, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorInsightsAPI] failed account_id=%s credential_id=%s", payload.account_id, payload.credential_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
