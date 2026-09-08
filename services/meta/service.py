"""MetaAdsService —— Meta API 统一封装层（设计文档第 19 节 / 原则六）

设计要点：
1. SDK 隔离：业务层只依赖本类，不直接 import facebook_business，
   Meta API 版本变化只需维护这一层。
2. 错误分类：所有异常统一转成 MetaApiError（AUTH/PERMISSION/VALIDATION/
   RATE_LIMIT/TEMPORARY/UNKNOWN），绝不 `except Exception: return None`。
3. 重试：仅对 RATE_LIMIT / TEMPORARY 做指数退避重试（2s → 4s → 8s），
   参数错误类直接失败（设计文档第 27 / 28 节）。
4. 限流：调用前按账户维度做窗口限流，超限则等待，
   Batch API 不能替代 Rate Limiting（设计文档第 25 / 26 节）。
"""
import json
import time
from typing import Any, Callable, Dict, List, Optional

import requests

from config.settings import settings
from core.enums import ErrorCategory
from core.logger import logger
from services.meta.client import MetaClient
from services.meta.errors import MetaApiError, classify, classify_facebook_error
from services.rate_limit import RateLimitManager


class MetaAdsService:
    """Meta 广告对象操作统一入口

    用法：
        service = MetaAdsService(MetaClient(access_token))
        campaign = service.create_campaign("123456", {...})
    """

    def __init__(
        self,
        client: MetaClient,
        *,
        max_retries: int = 3,
        backoff_base: int = 2,
        enable_rate_limit: bool = True,
        max_throttle_wait: int = 60,
    ):
        self.client = client
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.enable_rate_limit = enable_rate_limit
        self.max_throttle_wait = max_throttle_wait

    # ------------------------------------------------------------------
    # 统一调用包装：限流 + 错误分类 + 指数退避重试
    # ------------------------------------------------------------------
    def _throttle(self, account_id: Optional[str]) -> None:
        """调用前限流：超过分钟窗口则等待（而不是静默放行）"""
        if not self.enable_rate_limit or not account_id:
            return
        limiter = RateLimitManager(account_id)
        waited = 0
        while not limiter.check_limit("minute") and waited < self.max_throttle_wait:
            time.sleep(1)
            waited += 1
        if waited:
            logger.warning(f"[MetaAdsService] 账户 {account_id} 触发限流，等待 {waited}s")

    def _count_call(self, account_id: Optional[str]) -> None:
        """调用后计数"""
        if not self.enable_rate_limit or not account_id:
            return
        limiter = RateLimitManager(account_id)
        limiter.increment("minute")
        limiter.increment("hour")

    def _execute(
        self,
        fn: Callable[[], Any],
        description: str,
        account_id: Optional[str] = None,
    ) -> Any:
        """执行 Meta API 调用，统一处理限流、错误分类与重试"""
        last_err: Optional[MetaApiError] = None

        for attempt in range(self.max_retries + 1):
            self._throttle(account_id)
            try:
                result = fn()
                self._count_call(account_id)
                return result
            except MetaApiError as e:
                last_err = e
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = MetaApiError(str(e), category=ErrorCategory.TEMPORARY)
            except Exception as e:  # 含 FacebookRequestError
                last_err = classify_facebook_error(e)

            if last_err and not last_err.retryable:
                # 参数/权限/认证类错误：重试无意义，直接失败
                logger.error(f"[MetaAdsService] {description} 失败（不可重试）: {last_err}")
                break

            if attempt < self.max_retries:
                delay = self.backoff_base ** (attempt + 1)  # 2s → 4s → 8s
                logger.warning(
                    f"[MetaAdsService] {description} 第 {attempt + 1} 次失败，"
                    f"{delay}s 后重试: {last_err}"
                )
                time.sleep(delay)

        raise last_err or MetaApiError(f"{description} 失败：未知错误")

    # ------------------------------------------------------------------
    # 创建类接口（设计文档第 19 节推荐接口）
    # ------------------------------------------------------------------
    def create_campaign(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 Campaign。

        Campaign 创建使用直接 Graph API POST，而不是 SDK 的
        ``remote_create``。SDK 在当前 API 版本会对部分字段做额外序列化，
        导致 Meta 返回 code=100/subcode=4834011。这里只发送创建 Campaign
        所需的最小字段，AdSet/Creative/Ad 仍由后续步骤创建。
        """
        act = self.client.normalize_account_id(account_id)

        def _do():
            allowed = {"name", "objective", "status", "special_ad_categories", "buying_type"}
            payload = {key: value for key, value in (params or {}).items() if key in allowed}
            required = {"name", "objective", "status", "special_ad_categories"}
            missing = required.difference(payload)
            if missing:
                raise MetaApiError(
                    f"创建 Campaign 缺少必要参数: {', '.join(sorted(missing))}",
                    category=ErrorCategory.VALIDATION,
                )
            result = self.client._post(f"{act}/campaigns", payload)
            campaign_id = result.get("id")
            if not campaign_id:
                raise MetaApiError(
                    "Meta 创建 Campaign 未返回 id",
                    category=ErrorCategory.UNKNOWN,
                )
            return {"id": campaign_id}

        return self._execute(_do, f"create_campaign(act={act})", account_id=account_id)

    def create_adset(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 AdSet。params 需包含 campaign_id。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            result = self.client._post(f"{act}/adsets", params)
            return {"id": result["id"]}

        return self._execute(_do, f"create_adset(act={act})", account_id=account_id)

    def create_creative(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 AdCreative。params 需包含 name 与 object_story_spec。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            result = self.client._post(f"{act}/adcreatives", params)
            return {"id": result["id"]}

        return self._execute(_do, f"create_creative(act={act})", account_id=account_id)

    def create_ad(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 Ad。params 需包含 adset_id 与 creative。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            result = self.client._post(f"{act}/ads", params)
            return {"id": result["id"]}

        return self._execute(_do, f"create_ad(act={act})", account_id=account_id)

    def delete_object(self, object_id: str) -> Dict[str, Any]:
        """删除投放失败补偿阶段创建的 Meta 对象。"""
        return self._execute(lambda: self.client._delete(object_id), f"delete_object({object_id})")

    # ------------------------------------------------------------------
    # 批量操作 Action（设计文档第 22 / 23 节）
    # ------------------------------------------------------------------
    def update_budget(
        self, object_id: str, budget_usd: float, level: str = "adset"
    ) -> Dict[str, Any]:
        """修改预算。Meta 以「分」为单位。

        Args:
            level: adset（日预算）或 campaign
        """
        if budget_usd is None or budget_usd <= 0:
            raise MetaApiError(
                f"预算必须为正数，收到 {budget_usd}", category=ErrorCategory.VALIDATION
            )

        def _do():
            self.client._post(
                object_id,
                {"daily_budget": int(round(budget_usd * 100))},
            )
            return {"id": object_id, "daily_budget": budget_usd}

        return self._execute(_do, f"update_budget({level}={object_id})")

    def pause_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """暂停 Campaign"""
        return self._set_campaign_status(campaign_id, "PAUSED")

    def enable_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """启用 Campaign"""
        return self._set_campaign_status(campaign_id, "ACTIVE")

    def _set_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        def _do():
            self.client._post(campaign_id, {"status": status})
            return {"id": campaign_id, "status": status}

        return self._execute(_do, f"set_campaign_status({campaign_id}={status})")

    # ------------------------------------------------------------------
    # 读取与素材
    # ------------------------------------------------------------------
    def get_insights(self, account_id: str, params: Dict[str, Any]) -> List[Dict]:
        """拉取洞察数据（设计文档第 32 节：由 Sync Worker 落库，而非前端实时调用）"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            # facebook-business 18.0.0 在当前 App 配置下会错误返回
            # ``(#200) Provide valid app ID``，而同一 User Token 直接调用
            # Graph API 已验证可用。因此 Insights 走显式 HTTP 请求，
            # 仍然使用当前账户的 User Access Token，不使用全局 Token。
            date_preset = params.get("date_preset", "yesterday")
            request_params = {
                "level": params.get("level", "account"),
                "fields": params.get(
                    "fields",
                    "date_start,date_stop,spend,impressions,clicks,actions,"
                    "cost_per_action_type,ctr,cpc,cpm,frequency,reach,"
                    "account_id,campaign_id,adset_id,ad_id",
                ),
            }
            # Meta Graph API 不允许 date_preset=custom；自定义日期必须只传 time_range。
            if date_preset != "custom":
                request_params["date_preset"] = date_preset
            for key, value in params.items():
                if key not in {"date_preset", "level", "fields"}:
                    request_params[key] = value
            for key, value in list(request_params.items()):
                if isinstance(value, (dict, list)):
                    request_params[key] = json.dumps(value, separators=(",", ":"))

            rows: List[Dict[str, Any]] = []
            after = None
            for _ in range(20):
                page_params = dict(request_params)
                page_params["limit"] = min(int(page_params.get("limit", 500)), 500)
                if after:
                    page_params["after"] = after
                try:
                    response = requests.get(
                        f"https://graph.facebook.com/{settings.FB_API_VERSION}/{act}/insights",
                        params={**page_params, "access_token": self.client.access_token},
                        timeout=settings.FB_API_TIMEOUT,
                    )
                except (requests.Timeout, requests.ConnectionError) as exc:
                    raise MetaApiError(str(exc), category=ErrorCategory.TEMPORARY)

                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
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
                rows.extend(payload.get("data", []) if isinstance(payload, dict) else [])
                after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
                if not after:
                    break
            return rows

        return self._execute(_do, f"get_insights(act={act})", account_id=account_id)

    def get_ad_account(self, account_id: str) -> Dict[str, Any]:
        """读取广告账户信息"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            return self.client._get(
                act,
                params={
                    "fields": "id,name,currency,timezone_name,"
                    "account_status,disable_reason,"
                    "amount_spent,spend_cap",
                },
            )

        return self._execute(_do, f"get_ad_account(act={act})", account_id=account_id)

    def list_campaigns(self, account_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取广告账户下的 Campaign，供同步任务使用。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            fields = (
                "id,name,status,effective_status,objective,daily_budget,"
                "lifetime_budget,updated_time"
            )
            rows: List[Dict[str, Any]] = []
            after = None
            for _ in range(20):
                params = {"fields": fields, "limit": limit}
                if after:
                    params["after"] = after
                payload = self.client._get(f"{act}/campaigns", params=params)
                rows.extend(payload.get("data", []))
                after = (payload.get("paging") or {}).get("cursors", {}).get("after")
                if not after:
                    break
            return rows

        return self._execute(_do, f"list_campaigns(act={act})", account_id=account_id)

    def list_adsets(self, campaign_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取 Campaign 下的 AdSet。"""
        def _do():
            rows: List[Dict[str, Any]] = []
            after = None
            for _ in range(20):
                params = {
                    "fields": "id,name,status,effective_status,daily_budget,"
                              "lifetime_budget,optimization_goal,billing_event,"
                              "targeting,updated_time",
                    "limit": limit,
                }
                if after:
                    params["after"] = after
                payload = self.client._get(f"{campaign_id}/adsets", params)
                rows.extend(payload.get("data", []))
                after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
                if not after:
                    break
            return rows

        return self._execute(_do, f"list_adsets(campaign={campaign_id})")

    def list_ads(self, adset_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取 AdSet 下的 Ad。"""
        def _do():
            rows: List[Dict[str, Any]] = []
            after = None
            for _ in range(20):
                params = {
                    "fields": "id,name,status,effective_status,creative,updated_time",
                    "limit": limit,
                }
                if after:
                    params["after"] = after
                payload = self.client._get(f"{adset_id}/ads", params)
                rows.extend(payload.get("data", []))
                after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
                if not after:
                    break
            return rows

        return self._execute(_do, f"list_ads(adset={adset_id})")

    def update_campaign(self, campaign_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 Campaign 属性，例如名称、预算或状态。"""
        def _do():
            self.client._post(campaign_id, params)
            return {"id": campaign_id, **params}

        return self._execute(_do, f"update_campaign({campaign_id})")

    def update_adset(self, adset_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 AdSet 属性，例如预算、定向或状态。"""
        def _do():
            self.client._post(adset_id, params)
            return {"id": adset_id, **params}

        return self._execute(_do, f"update_adset({adset_id})")

    def update_ad(self, ad_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 Ad 属性，例如名称或状态。"""
        def _do():
            self.client._post(ad_id, params)
            return {"id": ad_id, **params}

        return self._execute(_do, f"update_ad({ad_id})")

    def upload_image(self, account_id: str, file_path: str) -> Dict[str, Any]:
        """上传图片素材，返回 image_hash"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            with open(file_path, "rb") as image_file:
                result = self.client._post(
                    f"{act}/adimages",
                    {},
                    files={"filename": image_file},
                )
            images = result.get("images") or {}
            first = next(iter(images.values()), {})
            image_hash = first.get("hash")
            if not image_hash:
                raise MetaApiError("Meta 图片上传未返回 hash", category=ErrorCategory.UNKNOWN)
            return {"hash": image_hash}

        return self._execute(_do, f"upload_image(act={act})", account_id=account_id)

    def upload_video(self, account_id: str, file_path: str) -> Dict[str, Any]:
        """上传视频素材，返回 video_id"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            with open(file_path, "rb") as video_file:
                result = self.client._post(
                    f"{act}/advideos",
                    {},
                    files={"source": video_file},
                )
            video_id = result.get("id")
            if not video_id:
                raise MetaApiError("Meta 视频上传未返回 id", category=ErrorCategory.UNKNOWN)
            return {"video_id": video_id}

        return self._execute(_do, f"upload_video(act={act})", account_id=account_id)

    def verify_account_under_bm(
        self, business_id: str, target_account_id: str
    ) -> Dict[str, Any]:
        """校验广告账户是否归属指定 BM（设计文档：BM → Ad Accounts 归属关系）"""
        target = (target_account_id or "").replace("act_", "")
        bm_id = business_id[2:] if business_id.startswith("bm") else business_id

        def _do():
            params = {"fields": "id,name", "limit": 200}
            after = None
            for _ in range(20):  # 最多翻 20 页，避免死循环
                if after:
                    params["after"] = after
                data = self.client._get(f"{bm_id}/adaccounts", params=params)
                for acc in data.get("data", []):
                    if acc.get("id", "").replace("act_", "") == target:
                        return {"verified": True, "account_name": acc.get("name")}
                after = data.get("paging", {}).get("cursors", {}).get("after")
                if not after:
                    break
            return {
                "verified": False,
                "error": f"广告账户 act_{target} 不在 BM({business_id}) 下",
            }

        return self._execute(
            _do, f"verify_account_under_bm(bm={bm_id}, act={target})"
        )
