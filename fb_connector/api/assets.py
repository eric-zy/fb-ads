"""海外 Connector 的 BM、广告账户和 Page 资产接口。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fb_connector.credential_store import DatabaseCredentialVault
from services.meta import MetaClient

router = APIRouter(prefix="/internal/meta", tags=["Meta Assets"])

class CredentialRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)

class BusinessRequest(CredentialRequest):
    business_id: str = Field(..., min_length=1, max_length=64)

class AccountVerifyRequest(BusinessRequest):
    account_id: str = Field(..., min_length=1, max_length=64)

def _client(credential_id: str) -> MetaClient:
    try:
        return MetaClient(access_token=DatabaseCredentialVault().get_access_token(credential_id))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="凭据不存在或已失效") from exc

@router.post("/business/verify")
async def verify_business(payload: BusinessRequest):
    try:
        return _client(payload.credential_id).get_business(payload.business_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/accounts/sync")
async def sync_accounts(payload: BusinessRequest):
    try:
        return {"business_id": payload.business_id, "accounts": _client(payload.credential_id).get_ad_accounts(payload.business_id)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/business/verify-account")
async def verify_account(payload: AccountVerifyRequest):
    try:
        client = _client(payload.credential_id)
        account = client.get_ad_account(payload.account_id)
        return {"ok": str(account.get("id", "")).replace("act_", "") == str(payload.account_id).replace("act_", ""), "account": account, "business_id": payload.business_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/pages/sync")
async def sync_pages(payload: CredentialRequest):
    # PageService 的同步需要国内 MetaAccount/数据库上下文；此接口先提供
    # Connector 侧的 Token 边界，具体 Page 结果格式在 T08 统一。
    try:
        client = _client(payload.credential_id)
        # 永远不请求/返回 Page Access Token；后续投放如需使用由 Connector 内部按 credential_id 获取。
        return {"credential_id": payload.credential_id, "pages": client._get("me/accounts", {"fields": "id,name,tasks", "limit": 100}).get("data", [])}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
