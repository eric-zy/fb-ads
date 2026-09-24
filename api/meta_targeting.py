"""Meta 受众定向目录接口。

该接口先提供可版本化语言目录和发布前定向校验；Custom Audience 同步由
账户级 Meta 资产接口接入，不能在没有账户上下文时生成“全局受众”。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from core.auth import get_current_active_user
from core.database import get_db
from config.settings import settings
from models import AdAccount, User
from services.account_access import can_access_account
from services.credential_service import CredentialService
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from services.meta import MetaApiError, MetaClient
from services.targeting_catalog import (
    TARGETING_SEARCH_TYPE_OPTIONS,
    normalize_targeting,
    search_languages,
)


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


def _search_item(raw: dict, search_type: str) -> dict:
    """把 Meta 各类 Search 返回压成下拉需要的稳定展示字段。"""
    item = dict(raw)
    key = item.get("id") or item.get("key") or item.get("value")
    name = (
        item.get("name")
        or item.get("label")
        or item.get("display_name")
        or item.get("title")
        or key
    )
    labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
    localized_name = (
        item.get("name_zh")
        or item.get("name_cn")
        or item.get("localized_name")
        or labels.get("zh_CN")
        or labels.get("zh-CN")
    )
    item["id"] = str(key) if key is not None else ""
    item["name"] = str(name or item["id"])
    if localized_name:
        item["name_zh"] = str(localized_name)
    item["search_type"] = search_type
    return item


@router.get("/search")
def search_targeting(
    account_pk: str = Query(..., description="系统广告账户主键，用于权限和凭据范围校验"),
    type: str = Query(..., description="Meta Targeting Search type"),
    q: str = Query("", max_length=255),
    locale: Optional[str] = Query(None, max_length=64),
    country_code: Optional[str] = Query(None, max_length=8),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """为前端远程下拉提供 Meta 官方定向目录搜索。"""
    search_type = str(type or "").strip().lower()
    if search_type not in TARGETING_SEARCH_TYPE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"不支持的 Meta 定向搜索类型：{type}")
    account = db.query(AdAccount).filter(AdAccount.id == account_pk).first()
    if not account:
        raise HTTPException(status_code=404, detail="广告账户不存在")
    if not can_access_account(db, current_user, account_pk):
        raise HTTPException(status_code=403, detail="无权访问该广告账户的 Meta 定向目录")
    try:
        connector_credential_id = account.connector_credential_id or (
            account.business.connector_credential_id if account.business else None
        )
        if settings.FB_ACCESS_MODE == "connector":
            if not connector_credential_id:
                raise ValueError("广告账户未绑定 Connector 凭据")
            payload = FBConnectorClient().search_targeting(
                account.account_id,
                connector_credential_id,
                search_type,
                q,
                locale=locale,
                country_code=country_code,
                limit=limit,
            )
        else:
            token, _ = CredentialService(db).resolve_account_token(account_pk)
            payload = MetaClient(token).search_targeting(
                search_type,
                q,
                locale=locale,
                country_code=country_code,
                limit=limit,
            )
    except Exception as exc:
        if isinstance(exc, MetaApiError) and exc.code == 100 and exc.subcode == 33:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "TARGETING_SEARCH_UNSUPPORTED",
                    "message": "Meta 当前不支持该目录查询，请输入更具体的关键词，或改用国家/地区和高级自定义位置。",
                    "search_type": search_type,
                },
            ) from exc
        if isinstance(exc, FBConnectorError) and exc.detail is not None:
            raise HTTPException(
                status_code=exc.status_code or 400,
                detail=exc.detail,
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raw_data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(raw_data, dict):
        raw_data = list(raw_data.values())
    items = [_search_item(item, search_type) for item in raw_data if isinstance(item, dict)]
    return {"items": items[:limit], "type": search_type, "account_pk": account_pk}


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
