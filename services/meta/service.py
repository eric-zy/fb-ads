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
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.adimage import AdImage
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.advideo import AdVideo
from facebook_business.adobjects.campaign import Campaign

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
        """创建 Campaign。params 为 Meta 原生字段字典。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            campaign = Campaign(parent_id=act, api=self.client.api)
            campaign.update(params)
            campaign.remote_create()
            return {"id": campaign.get_id()}

        return self._execute(_do, f"create_campaign(act={act})", account_id=account_id)

    def create_adset(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 AdSet。params 需包含 campaign_id。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            adset = AdSet(parent_id=act, api=self.client.api)
            adset.update(params)
            adset.remote_create()
            return {"id": adset.get_id()}

        return self._execute(_do, f"create_adset(act={act})", account_id=account_id)

    def create_creative(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 AdCreative。params 需包含 name 与 object_story_spec。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            creative = AdCreative(parent_id=act, api=self.client.api)
            creative.update(params)
            creative.remote_create()
            return {"id": creative.get_id()}

        return self._execute(_do, f"create_creative(act={act})", account_id=account_id)

    def create_ad(self, account_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建 Ad。params 需包含 adset_id 与 creative。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            ad = Ad(parent_id=act, api=self.client.api)
            ad.update(params)
            ad.remote_create()
            return {"id": ad.get_id()}

        return self._execute(_do, f"create_ad(act={act})", account_id=account_id)

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
            if level == "campaign":
                obj = Campaign(object_id, api=self.client.api)
            else:
                obj = AdSet(object_id, api=self.client.api)
            obj.update({AdSet.Field.daily_budget: int(round(budget_usd * 100))})
            obj.remote_update()
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
            campaign = Campaign(campaign_id, api=self.client.api)
            campaign.update({Campaign.Field.status: status})
            campaign.remote_update()
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

            try:
                response = requests.get(
                    f"https://graph.facebook.com/{settings.FB_API_VERSION}/{act}/insights",
                    params={
                        **request_params,
                        "access_token": self.client.access_token,
                    },
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
            return payload.get("data", []) if isinstance(payload, dict) else []

        return self._execute(_do, f"get_insights(act={act})", account_id=account_id)

    def get_ad_account(self, account_id: str) -> Dict[str, Any]:
        """读取广告账户信息"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            account = self.client.account(account_id)
            account.remote_read(
                fields=[
                    "id", "name", "currency", "timezone", "timezone_name",
                    "account_status", "effective_status", "disable_reason",
                    "amount_spent", "spend_cap",
                ]
            )
            return dict(account)

        return self._execute(_do, f"get_ad_account(act={act})", account_id=account_id)

    def list_campaigns(self, account_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取广告账户下的 Campaign，供同步任务使用。"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            account = self.client.account(account_id)
            rows = account.get_campaigns(
                fields=[
                    Campaign.Field.id,
                    Campaign.Field.name,
                    Campaign.Field.status,
                    Campaign.Field.effective_status,
                    Campaign.Field.objective,
                    Campaign.Field.daily_budget,
                    Campaign.Field.lifetime_budget,
                    Campaign.Field.updated_time,
                ],
                params={"limit": limit},
            )
            return [dict(row) for row in rows]

        return self._execute(_do, f"list_campaigns(act={act})", account_id=account_id)

    def list_adsets(self, campaign_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取 Campaign 下的 AdSet。"""
        def _do():
            campaign = Campaign(campaign_id, api=self.client.api)
            rows = campaign.get_ad_sets(
                fields=[
                    AdSet.Field.id,
                    AdSet.Field.name,
                    AdSet.Field.status,
                    AdSet.Field.effective_status,
                    AdSet.Field.daily_budget,
                    AdSet.Field.lifetime_budget,
                    AdSet.Field.optimization_goal,
                    AdSet.Field.billing_event,
                    AdSet.Field.targeting,
                    AdSet.Field.updated_time,
                ],
                params={"limit": limit},
            )
            return [dict(row) for row in rows]

        return self._execute(_do, f"list_adsets(campaign={campaign_id})")

    def list_ads(self, adset_id: str, *, limit: int = 100) -> List[Dict[str, Any]]:
        """读取 AdSet 下的 Ad。"""
        def _do():
            adset = AdSet(adset_id, api=self.client.api)
            rows = adset.get_ads(
                fields=[
                    Ad.Field.id,
                    Ad.Field.name,
                    Ad.Field.status,
                    Ad.Field.effective_status,
                    Ad.Field.creative,
                    Ad.Field.updated_time,
                ],
                params={"limit": limit},
            )
            return [dict(row) for row in rows]

        return self._execute(_do, f"list_ads(adset={adset_id})")

    def update_campaign(self, campaign_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 Campaign 属性，例如名称、预算或状态。"""
        def _do():
            campaign = Campaign(campaign_id, api=self.client.api)
            campaign.update(params)
            campaign.remote_update()
            return {"id": campaign_id, **params}

        return self._execute(_do, f"update_campaign({campaign_id})")

    def update_adset(self, adset_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 AdSet 属性，例如预算、定向或状态。"""
        def _do():
            adset = AdSet(adset_id, api=self.client.api)
            adset.update(params)
            adset.remote_update()
            return {"id": adset_id, **params}

        return self._execute(_do, f"update_adset({adset_id})")

    def update_ad(self, ad_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """更新 Ad 属性，例如名称或状态。"""
        def _do():
            ad = Ad(ad_id, api=self.client.api)
            ad.update(params)
            ad.remote_update()
            return {"id": ad_id, **params}

        return self._execute(_do, f"update_ad({ad_id})")

    def upload_image(self, account_id: str, file_path: str) -> Dict[str, Any]:
        """上传图片素材，返回 image_hash"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            image = AdImage(parent_id=act, api=self.client.api)
            image[AdImage.Field.filename] = file_path
            image.remote_create()
            return {"hash": image[AdImage.Field.hash]}

        return self._execute(_do, f"upload_image(act={act})", account_id=account_id)

    def upload_video(self, account_id: str, file_path: str) -> Dict[str, Any]:
        """上传视频素材，返回 video_id"""
        act = self.client.normalize_account_id(account_id)

        def _do():
            video = AdVideo(parent_id=act, api=self.client.api)
            video[AdVideo.Field.filepath] = file_path
            video.remote_create()
            return {"video_id": video.get_id()}

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
                response = self.client.api.call("GET", f"{bm_id}/adaccounts", params=params)
                data = response.json()
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
