"""Meta API 客户端（设计文档第 20 节）

关键设计（修正原有实现的根本缺陷）：
    services/fb_client.py 中的 FacebookClient 是**全局单例**，
    在 __init__ 里用 settings.FB_ACCESS_TOKEN 做全局初始化。
    这意味着系统只能用一个 Token 访问所有账户 —— 与"多 BM / 多广告账户"
    的核心场景直接冲突。

本实现为每个账户/BM 构造**独立的 Session 与 Api 实例**，
不使用 FacebookAdsApi.init()（它是全局的，在 Celery 并发 worker 下会串号），
而是把 api 实例显式传给每个 SDK 对象，保证多账户并发安全。
"""
import json
from typing import List, Optional

import requests

from facebook_business.api import FacebookAdsApi, FacebookSession
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount

from config.settings import settings
from core.logger import logger
from services.meta.errors import MetaApiError, classify, classify_facebook_error
from core.enums import ErrorCategory


class MetaClient:
    """面向单个凭据（Token）的 Meta API 客户端

    用法：
        client = MetaClient(access_token=bm_token)
        account = client.account("123456")
    """

    def __init__(
        self,
        access_token: str,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ):
        if not access_token:
            raise MetaApiError(
                "access_token 为空，无法初始化 Meta 客户端",
                category=ErrorCategory.AUTH,
            )

        self.access_token = access_token
        self.app_id = app_id or settings.FB_APP_ID
        self.app_secret = app_secret or settings.FB_APP_SECRET

        try:
            session = FacebookSession(
                app_id=self.app_id,
                app_secret=self.app_secret,
                access_token=self.access_token,
            )
            # 构造独立 Api 实例，不调用 FacebookAdsApi.init()（避免全局污染）
            self._api = FacebookAdsApi(
                session,
                api_version=settings.FB_API_VERSION,
            )
        except Exception as e:
            logger.error(f"[MetaClient] 初始化失败: {e}")
            raise MetaApiError(f"Meta 客户端初始化失败: {e}", category=ErrorCategory.AUTH)

    @property
    def api(self) -> FacebookAdsApi:
        return self._api

    @staticmethod
    def normalize_account_id(account_id: str) -> str:
        """统一广告账户 ID 前缀：123456 → act_123456"""
        account_id = (account_id or "").strip()
        if not account_id:
            raise MetaApiError("account_id 不能为空", category=ErrorCategory.VALIDATION)
        return account_id if account_id.startswith("act_") else f"act_{account_id}"

    def account(self, account_id: str) -> FBAdAccount:
        """获取绑定本客户端凭据的广告账户对象"""
        act = self.normalize_account_id(account_id)
        return FBAdAccount(act, self._api)

    # ------------------------------------------------------------------
    # Meta 账号管理 V1（设计文档 §22）
    # 所有 Meta API 调用统一从这里经过，便于 Token / 版本 / 重试 / 限流 / 错误映射
    # ------------------------------------------------------------------
    @staticmethod
    def normalize_business_id(business_id: str) -> str:
        """统一 BM ID 前缀：123456 → 123456（Graph API 直接用纯数字）"""
        bid = (business_id or "").strip()
        if not bid:
            raise MetaApiError("business_id 不能为空", category=ErrorCategory.VALIDATION)
        return bid[2:] if bid.startswith("bm") else bid

    def _get(self, path: str, params: dict) -> dict:
        """统一的 GET 调用与错误映射"""
        try:
            request_params = dict(params or {})
            for key, value in list(request_params.items()):
                if isinstance(value, (dict, list)):
                    request_params[key] = json.dumps(value, separators=(",", ":"))
            request_params["access_token"] = self.access_token
            response = requests.get(
                f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                params=request_params,
                timeout=settings.FB_API_TIMEOUT,
            )
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                code = error.get("code")
                subcode = error.get("error_subcode")
                raise MetaApiError(
                    error.get("message", f"Graph API HTTP {response.status_code}"),
                    category=classify(code, subcode, response.status_code),
                    code=code,
                    subcode=subcode,
                    http_status=response.status_code,
                    fbtrace_id=error.get("fbtrace_id"),
                )
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            raise classify_facebook_error(exc)

    def _post(self, path: str, params: dict, files: Optional[dict] = None) -> dict:
        """统一的 Graph API POST 调用与错误映射。

        写入接口使用账户凭证对应的 User Access Token；不使用全局
        FB_ACCESS_TOKEN。列表/字典参数按 Graph API 的表单格式序列化。
        """
        try:
            request_params = dict(params or {})
            for key, value in list(request_params.items()):
                if isinstance(value, (dict, list)):
                    request_params[key] = json.dumps(value, separators=(",", ":"))
            request_params["access_token"] = self.access_token
            response = requests.post(
                f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                data=request_params,
                files=files,
                timeout=settings.FB_API_TIMEOUT,
            )
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                code = error.get("code")
                subcode = error.get("error_subcode")
                raise MetaApiError(
                    error.get("message", f"Graph API HTTP {response.status_code}"),
                    category=classify(code, subcode, response.status_code),
                    code=code,
                    subcode=subcode,
                    http_status=response.status_code,
                    fbtrace_id=error.get("fbtrace_id"),
                )
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            raise classify_facebook_error(exc)

    def _delete(self, path: str) -> dict:
        """删除 Meta 对象（仅用于投放失败补偿，不作为业务删除入口）。"""
        try:
            response = requests.delete(
                f"https://graph.facebook.com/{settings.FB_API_VERSION}/{path.lstrip('/')}",
                params={"access_token": self.access_token},
                timeout=settings.FB_API_TIMEOUT,
            )
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if response.status_code >= 400 or error:
                error = error or {}
                raise MetaApiError(error.get("message", f"Graph API HTTP {response.status_code}"), category=classify(error.get("code"), error.get("error_subcode"), response.status_code))
            return payload
        except MetaApiError:
            raise
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)
        except Exception as exc:
            raise classify_facebook_error(exc)

    def get_business(self, business_id: str) -> dict:
        """拉取 BM 基础信息（文档 §14 添加 BM 时用于校验 Business ID）"""
        bid = self.normalize_business_id(business_id)
        return self._get(
            bid,
            params={"fields": "id,name,timezone_id,currency,created_time"},
        )

    def get_ad_accounts(self, business_id: str, max_pages: int = 20) -> List[dict]:
        """分页拉取 BM 下的广告账户（文档 §23 同步流程的 Meta 侧入口）"""
        bid = self.normalize_business_id(business_id)
        path = f"{bid}/adaccounts"
        params = {
            "fields": "id,name,account_status,effective_status,currency,timezone_name,"
                      "spend_cap,amount_spent,balance,disable_reason",
            "limit": 200,
        }

        accounts: List[dict] = []
        after = None
        for _ in range(max_pages):
            if after:
                params["after"] = after
            data = self._get(path, params)
            accounts.extend(data.get("data", []))
            paging = data.get("paging", {}) or {}
            after = (paging.get("cursors") or {}).get("after")
            if not after:
                break
        return accounts

    def get_ad_account(self, account_id: str) -> dict:
        """拉取单个广告账户的 Meta 侧信息（文档 §23 单账户同步）"""
        act = self.normalize_account_id(account_id)
        return self._get(
            f"/{act}",
            params={
                "fields": "id,name,account_status,effective_status,currency,"
                          "timezone_name,spend_cap,amount_spent,balance,disable_reason",
            },
        )
