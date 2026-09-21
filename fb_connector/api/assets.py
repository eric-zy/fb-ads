"""海外 Connector 的 BM、广告账户和 Page 资产接口。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fb_connector.credential_store import DatabaseCredentialVault, report_meta_auth_failure
from core.logger import logger
from services.meta import MetaClient

router = APIRouter(prefix="/internal/meta", tags=["Meta Assets"])

class CredentialRequest(BaseModel):
    credential_id: str = Field(..., min_length=1, max_length=50)

class BusinessRequest(CredentialRequest):
    business_id: str = Field(..., min_length=1, max_length=64)

class AccountVerifyRequest(BusinessRequest):
    account_id: str = Field(..., min_length=1, max_length=64)

class AudienceListRequest(CredentialRequest):
    account_id: str = Field(..., min_length=1, max_length=64)

def _client(credential_id: str) -> MetaClient:
    try:
        return MetaClient(access_token=DatabaseCredentialVault().get_access_token(credential_id))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="凭据不存在或已失效") from exc

@router.post("/business/verify")
async def verify_business(payload: BusinessRequest):
    logger.info("[ConnectorAssets] verify business start credential_id=%s business_id=%s", payload.credential_id, payload.business_id)
    try:
        result = _client(payload.credential_id).get_business(payload.business_id)
        logger.info("[ConnectorAssets] verify business success business_id=%s", payload.business_id)
        return result
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorAssets] verify business failed business_id=%s", payload.business_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/accounts/sync")
async def sync_accounts(payload: BusinessRequest):
    logger.info("[ConnectorAssets] sync accounts start credential_id=%s business_id=%s", payload.credential_id, payload.business_id)
    try:
        accounts = _client(payload.credential_id).get_ad_accounts(payload.business_id)
        logger.info("[ConnectorAssets] sync accounts success business_id=%s count=%s", payload.business_id, len(accounts))
        return {"business_id": payload.business_id, "accounts": accounts}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorAssets] sync accounts failed business_id=%s", payload.business_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/business/verify-account")
async def verify_account(payload: AccountVerifyRequest):
    logger.info("[ConnectorAssets] verify account start credential_id=%s account_id=%s", payload.credential_id, payload.account_id)
    try:
        client = _client(payload.credential_id)
        account = client.get_ad_account(payload.account_id)
        result = {"ok": str(account.get("id", "")).replace("act_", "") == str(payload.account_id).replace("act_", ""), "account": account, "business_id": payload.business_id}
        logger.info("[ConnectorAssets] verify account success account_id=%s", payload.account_id)
        return result
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorAssets] verify account failed account_id=%s", payload.account_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/pages/sync")
async def sync_pages(payload: CredentialRequest):
    # PageService 的同步需要国内 MetaAccount/数据库上下文；Connector 只负责
    # 使用托管的 User Token 拉取 Page 元数据，不返回 Page Access Token。
    try:
        logger.info("[ConnectorAssets] sync pages start credential_id=%s", payload.credential_id)
        client = _client(payload.credential_id)
        params = {"fields": "id,name,category,tasks", "limit": 100}
        pages = []
        for _ in range(20):
            # 永远不请求/返回 Page Access Token；后续投放由 Connector
            # 内部按 credential_id 获取对应授权。
            result = client._get("me/accounts", params)
            pages.extend(result.get("data", []))
            after = (result.get("paging") or {}).get("cursors", {}).get("after")
            if not after:
                break
            params["after"] = after
        logger.info("[ConnectorAssets] sync pages success credential_id=%s count=%s", payload.credential_id, len(pages))
        return {"credential_id": payload.credential_id, "pages": pages}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception("[ConnectorAssets] sync pages failed credential_id=%s", payload.credential_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/audiences/list")
async def list_custom_audiences(payload: AudienceListRequest):
    """返回广告账户可访问的 Custom Audience 元数据。

    Connector 只持有海外凭据，因此由 Connector 访问 Graph API；响应严格
    限定为受众名称、类型和投放/共享状态，不读取或返回受众成员数据。
    """
    try:
        logger.info(
            "[ConnectorAssets] list audiences start credential_id=%s account_id=%s",
            payload.credential_id,
            payload.account_id,
        )
        audiences = _client(payload.credential_id).get_custom_audiences(payload.account_id)
        logger.info(
            "[ConnectorAssets] list audiences success credential_id=%s account_id=%s count=%s",
            payload.credential_id,
            payload.account_id,
            len(audiences),
        )
        return {"account_id": payload.account_id, "audiences": audiences}
    except Exception as exc:
        report_meta_auth_failure(payload.credential_id, exc)
        logger.exception(
            "[ConnectorAssets] list audiences failed credential_id=%s account_id=%s",
            payload.credential_id,
            payload.account_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
