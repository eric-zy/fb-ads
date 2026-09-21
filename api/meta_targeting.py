"""Meta 受众定向目录接口。

该接口先提供可版本化语言目录和发布前定向校验；Custom Audience 同步由
账户级 Meta 资产接口接入，不能在没有账户上下文时生成“全局受众”。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth import get_current_active_user
from services.targeting_catalog import normalize_targeting, search_languages


router = APIRouter(prefix="/api/v1/meta-targeting", tags=["Meta 定向"])


@router.get("/languages")
def list_languages(
    q: Optional[str] = Query(None, description="语言名称、英文名、代码或 Meta ID"),
    limit: int = Query(50, ge=1, le=100),
    _: object = Depends(get_current_active_user),
):
    return {
        "items": search_languages(q, limit),
        "mode": "CATALOG",
        "message": "语言目录用于筛选；实际账户是否支持由发布前能力校验决定",
    }


class TargetingValidateRequest(BaseModel):
    targeting: Dict[str, Any] = Field(default_factory=dict)


@router.post("/validate")
def validate_targeting(
    req: TargetingValidateRequest,
    _: object = Depends(get_current_active_user),
):
    try:
        targeting = normalize_targeting(req.targeting)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"valid": True, "targeting": targeting}

