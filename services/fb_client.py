from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
from facebook_business.adobjects.campaign import Campaign as FBCampaign
from facebook_business.adobjects.ad import Ad as FBAd
from config.settings import settings
from core.logger import logger
from typing import List, Dict, Optional, Any
import time

class FacebookClient:
    """Facebook API 客户端封装"""
    
    def __init__(self):
        try:
            FacebookAdsApi.init(
                app_id=settings.FB_APP_ID,
                access_token=settings.FB_ACCESS_TOKEN,
                app_secret=settings.FB_APP_SECRET,
            )
            logger.info("Facebook API initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Facebook API: {str(e)}")
            raise
    
    def get_ad_account(self, account_id: str) -> Optional[FBAdAccount]:
        """获取广告账户"""
        try:
            account_id_with_prefix = f"act_{account_id}" if not account_id.startswith('act_') else account_id
            ad_account = FBAdAccount(account_id_with_prefix)
            fields = ['id', 'name', 'currency', 'timezone', 'account_status']
            ad_account.remote_read(fields=fields)
            return ad_account
        except Exception as e:
            logger.error(f"Failed to get ad account {account_id}: {str(e)}")
            return None
    
    def get_campaigns(self, account_id: str, params: Optional[Dict] = None) -> List[Dict]:
        """获取所有活跃系列"""
        try:
            account_id_with_prefix = f"act_{account_id}" if not account_id.startswith('act_') else account_id
            ad_account = FBAdAccount(account_id_with_prefix)
            
            fields = [
                'id', 'name', 'objective', 'status', 'budget_rebalance_flag',
                'budgets', 'daily_budget', 'lifetime_budget', 'start_time', 'stop_time'
            ]
            
            campaigns = ad_account.get_campaigns(
                fields=fields,
                params=params or {}
            )
            
            result = []
            for campaign in campaigns:
                result.append(dict(campaign))
            
            return result
        except Exception as e:
            logger.error(f"Failed to get campaigns for account {account_id}: {str(e)}")
            return []
    
    def get_insights(self, account_id: str, date_start: str, date_stop: str, 
                     level: str = 'account', params: Optional[Dict] = None) -> List[Dict]:
        """获取洞察数据 (insights)
        
        Args:
            account_id: 广告账户ID
            date_start: 开始日期 (YYYY-MM-DD)
            date_stop: 结束日期 (YYYY-MM-DD)
            level: 数据级别 (account, campaign, ad, adset)
            params: 额外参数
        """
        try:
            account_id_with_prefix = f"act_{account_id}" if not account_id.startswith('act_') else account_id
            ad_account = FBAdAccount(account_id_with_prefix)
            
            fields = [
                'date_start', 'date_stop', 'spend', 'impressions', 'clicks',
                'actions', 'cost_per_action_type', 'ctr', 'cpc', 'cpm',
                'frequency', 'reach', 'account_id', 'campaign_id', 'adset_id', 'ad_id'
            ]
            
            request_params = {
                'date_preset': 'custom',
                'time_range': {'since': date_start, 'until': date_stop},
                'level': level,
                'fields': fields
            }
            
            if params:
                request_params.update(params)
            
            insights = ad_account.get_insights(params=request_params)
            
            result = []
            for insight in insights:
                result.append(dict(insight))
            
            return result
        except Exception as e:
            logger.error(f"Failed to get insights for account {account_id}: {str(e)}")
            return []
    
    def pause_campaign(self, campaign_id: str) -> bool:
        """暂停系列"""
        try:
            campaign = FBCampaign(campaign_id)
            campaign.update({FBCampaign.Field.status: FBCampaign.Status.paused})
            logger.info(f"Campaign {campaign_id} paused successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to pause campaign {campaign_id}: {str(e)}")
            return False
    
    def resume_campaign(self, campaign_id: str) -> bool:
        """恢复系列"""
        try:
            campaign = FBCampaign(campaign_id)
            campaign.update({FBCampaign.Field.status: FBCampaign.Status.active})
            logger.info(f"Campaign {campaign_id} resumed successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to resume campaign {campaign_id}: {str(e)}")
            return False
    
    def update_campaign_budget(self, campaign_id: str, daily_budget: float) -> bool:
        """更新系列日预算"""
        try:
            campaign = FBCampaign(campaign_id)
            campaign.update({FBCampaign.Field.daily_budget: int(daily_budget * 100)})  # Facebook使用分为单位
            logger.info(f"Campaign {campaign_id} budget updated to {daily_budget}")
            return True
        except Exception as e:
            logger.error(f"Failed to update campaign {campaign_id} budget: {str(e)}")
            return False
    
    def retry_api_call(self, func, max_retries: int = 3, backoff_factor: float = 1.0):
        """带重试的API调用"""
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"API call failed after {max_retries} attempts: {str(e)}")
                    raise
                
                wait_time = backoff_factor * (2 ** attempt)
                logger.warning(f"API call failed, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)

    def list_bm_ad_accounts(
        self,
        business_id: str,
        access_token: str,
        stop_at_account_id: str = None,
    ) -> Dict[str, Any]:
        """分页拉取某个 Business Manager 下的广告账户列表

        Args:
            business_id: BM ID
            access_token: 该 BM 的 Access Token
            stop_at_account_id: 命中该账户即可提前停止翻页（归属校验场景）；
                                为空则拉取全部（同步场景）

        返回:
            {
                "ok": bool,          # 调用是否成功
                "dev_mode": bool,    # 是否开发降级模式
                "error": str | None,
                "accounts": [{"id","name","account_status","currency"}, ...]
            }
        """
        # 开发降级：未配置真实 FB 凭据或 SDK 不可用时，放行以便本地开发测试
        if not settings.FB_ACCESS_TOKEN or not access_token:
            logger.warning(
                f"[DEV] 未配置 FB 凭据，跳过拉取 BM {business_id} 的广告账户（开发模式）"
            )
            return {"ok": True, "dev_mode": True, "error": None, "accounts": []}

        try:
            from facebook_business.api import FacebookSession, FacebookAdsApi
            from facebook_business.exceptions import FacebookRequestError
        except Exception as e:
            logger.warning(f"[DEV] facebook_business 不可用，降级放行: {e}")
            return {"ok": True, "dev_mode": True, "error": None, "accounts": []}

        accounts = []
        target = (stop_at_account_id or "").replace("act_", "")

        try:
            session = FacebookSession(
                settings.FB_APP_ID, settings.FB_APP_SECRET, access_token
            )
            api = FacebookAdsApi(session)
            bm_id = business_id.replace("bm", "") if business_id.startswith("bm") else business_id

            url = f"{bm_id}/adaccounts"
            params = {
                "fields": "id,name,account_status,currency",
                "limit": 200,
            }
            after = None
            for _ in range(20):  # 最多翻 20 页，避免死循环
                if after:
                    params["after"] = after
                response = api.call("GET", url, params=params)
                data = response.json()
                for acc in data.get("data", []):
                    acc_id = acc.get("id", "").replace("act_", "")
                    accounts.append(
                        {
                            "id": acc_id,
                            "name": acc.get("name"),
                            "account_status": acc.get("account_status"),
                            "currency": acc.get("currency"),
                        }
                    )
                    if target and acc_id == target:
                        # 归属校验命中即停，避免大 BM 下无谓翻页
                        return {
                            "ok": True,
                            "dev_mode": False,
                            "error": None,
                            "accounts": accounts,
                        }
                paging = data.get("paging", {})
                after = paging.get("cursors", {}).get("after")
                if not after:
                    break

            return {"ok": True, "dev_mode": False, "error": None, "accounts": accounts}

        except FacebookRequestError as e:
            msg = ""
            try:
                msg = e.api_error_message()
            except Exception:
                msg = str(e)
            logger.error(f"拉取 BM {business_id} 广告账户失败: {msg}")
            return {"ok": False, "dev_mode": False, "error": f"BM 请求失败: {msg}", "accounts": []}
        except Exception as e:
            logger.error(f"拉取 BM {business_id} 广告账户异常: {str(e)}")
            return {"ok": False, "dev_mode": False, "error": f"请求异常: {str(e)}", "accounts": []}

    def verify_account_under_bm(
        self, business_id: str, access_token: str, target_account_id: str
    ) -> Dict[str, Any]:
        """验证某个广告账户是否归属于指定的 Business Manager（主账号）

        用该 BM 的 access_token 调用 Graph API 拉取 BM 下的广告账户列表，
        确认目标 account_id 包含在内。

        返回:
            {
                "verified": bool,       # 是否归属该 BM
                "dev_mode": bool,       # 是否为开发降级模式（未配置真实 FB 时）
                "error": str | None,    # 失败原因
                "account_name": str | None  # 命中时返回 FB 中的账户名
            }
        """
        target = target_account_id.replace("act_", "")

        result = self.list_bm_ad_accounts(
            business_id=business_id,
            access_token=access_token,
            stop_at_account_id=target,
        )

        # 开发降级：未配置真实 FB 凭据或 SDK 不可用时，放行以便本地开发测试
        if result["dev_mode"]:
            return {
                "verified": True,
                "dev_mode": True,
                "error": None,
                "account_name": None,
            }

        if not result["ok"]:
            return {
                "verified": False,
                "dev_mode": False,
                "error": result["error"],
                "account_name": None,
            }

        for acc in result["accounts"]:
            if acc["id"] == target:
                return {
                    "verified": True,
                    "dev_mode": False,
                    "error": None,
                    "account_name": acc.get("name"),
                }

        return {
            "verified": False,
            "dev_mode": False,
            "error": f"广告账户 act_{target} 不在该 Business Manager ({business_id}) 下",
            "account_name": None,
        }

    def upload_image(self, account_id: str, access_token: str, file_path: str) -> Dict[str, Any]:
        """上传图片素材到 Facebook，返回 image_hash

        降级：未配置真实 FB 时返回占位 hash，便于本地开发测试。
        """
        target = account_id.replace("act_", "")
        act = f"act_{target}"

        if not settings.FB_ACCESS_TOKEN or not access_token:
            logger.warning("[DEV] 未配置 FB 凭据，跳过图片上传（开发模式返回占位 hash）")
            return {"hash": f"dev_hash_{target}_{int(__import__('time').time())}", "dev_mode": True}

        try:
            from facebook_business.api import FacebookSession, FacebookAdsApi
            from facebook_business.adobjects.adaccount import AdAccount
            from facebook_business.adobjects.adimage import AdImage
        except Exception as e:
            logger.warning(f"[DEV] facebook_business 不可用，降级: {e}")
            return {"hash": f"dev_hash_{target}", "dev_mode": True}

        try:
            session = FacebookSession(settings.FB_APP_ID, settings.FB_APP_SECRET, access_token)
            api = FacebookAdsApi(session)
            img = AdImage(act, api)
            img[AdImage.Field.filename] = file_path
            res = img.remote_create()
            h = res.get("hash") if isinstance(res, dict) else getattr(res, "get", lambda k: None)("hash")
            return {"hash": h, "dev_mode": False}
        except Exception as e:
            logger.error(f"图片上传失败: {str(e)}")
            return {"hash": None, "dev_mode": False, "error": str(e)}

    def upload_video(self, account_id: str, access_token: str, file_path: str) -> Dict[str, Any]:
        """上传视频素材到 Facebook，返回 video_id

        降级：未配置真实 FB 时返回占位 video_id。
        """
        target = account_id.replace("act_", "")
        act = f"act_{target}"

        if not settings.FB_ACCESS_TOKEN or not access_token:
            logger.warning("[DEV] 未配置 FB 凭据，跳过视频上传（开发模式返回占位 video_id）")
            return {"video_id": f"dev_video_{target}_{int(__import__('time').time())}", "dev_mode": True}

        try:
            from facebook_business.api import FacebookSession, FacebookAdsApi
            from facebook_business.adobjects.adaccount import AdAccount
            from facebook_business.adobjects.advideo import AdVideo
            from facebook_business.video_uploader import VideoUploader
        except Exception as e:
            logger.warning(f"[DEV] facebook_business 不可用，降级: {e}")
            return {"video_id": f"dev_video_{target}", "dev_mode": True}

        try:
            session = FacebookSession(settings.FB_APP_ID, settings.FB_APP_SECRET, access_token)
            api = FacebookAdsApi(session)
            video = AdVideo(act, api)
            video[AdVideo.Field.filepath] = file_path
            VideoUploader().upload(video, wait_for_encoding=False)
            return {"video_id": video.get("id") or video.get_id(), "dev_mode": False}
        except Exception as e:
            logger.error(f"视频上传失败: {str(e)}")
            return {"video_id": None, "dev_mode": False, "error": str(e)}

    def publish_combo(
        self,
        account_id: str,
        access_token: str,
        *,
        name_prefix: str,
        objective: str,
        daily_budget: float,
        asset_type: str,           # 'image' | 'video'
        image_hash: str | None = None,
        video_id: str | None = None,
        headline: str,
        body: str,
        idx: int = 0,
    ) -> Dict[str, Any]:
        """为一个「账户 × 素材 × 文案」组合创建 Campaign + AdSet + Ad。

        真实 FB：依次创建三个对象（creative 引用 image_hash 或 video_id）。
        降级：未配置 FB 时返回占位 id，便于本地开发。

        返回: {"campaign_id","adset_id","ad_id","dev_mode","error"}
        """
        target = account_id.replace("act_", "")
        act = f"act_{target}"
        ts = int(__import__('time').time())

        if not settings.FB_ACCESS_TOKEN or not access_token:
            logger.warning("[DEV] 未配置 FB 凭据，跳过真实发布（开发模式返回占位 id）")
            return {
                "campaign_id": f"dev_camp_{target}_{ts}_{idx}",
                "adset_id": f"dev_set_{target}_{ts}_{idx}",
                "ad_id": f"dev_ad_{target}_{ts}_{idx}",
                "dev_mode": True,
                "error": None,
            }

        try:
            from facebook_business.api import FacebookSession, FacebookAdsApi
            from facebook_business.adobjects.adaccount import AdAccount as FBAdAccount
            from facebook_business.adobjects.campaign import Campaign as FBCampaign
            from facebook_business.adobjects.adset import AdSet
            from facebook_business.adobjects.ad import Ad as FBAd
            from facebook_business.adobjects.adcreative import AdCreative
        except Exception as e:
            logger.warning(f"[DEV] facebook_business 不可用，降级: {e}")
            return {
                "campaign_id": f"dev_camp_{target}_{ts}_{idx}",
                "adset_id": f"dev_set_{target}_{ts}_{idx}",
                "ad_id": f"dev_ad_{target}_{ts}_{idx}",
                "dev_mode": True,
                "error": None,
            }

        try:
            session = FacebookSession(settings.FB_APP_ID, settings.FB_APP_SECRET, access_token)
            api = FacebookAdsApi(session)
            fb_account = FBAdAccount(act, api)

            camp_name = f"{name_prefix} C{idx}"
            set_name = f"{name_prefix} S{idx}"
            ad_name = f"{name_prefix} A{idx}"

            # 1) Campaign
            campaign = FBCampaign(api=api)
            campaign[Campaign.Field.name] = camp_name
            campaign[Campaign.Field.objective] = objective
            campaign[Campaign.Field.status] = FBCampaign.Status.active
            campaign[Campaign.Field.special_ad_categories] = []
            campaign.remote_create(parent_id=fb_account.get_id_assured())

            # 2) AdSet
            adset = AdSet(api=api)
            adset[AdSet.Field.name] = set_name
            adset[AdSet.Field.campaign_id] = campaign.get_id()
            adset[AdSet.Field.billing_event] = AdSet.BillingEvent.impressions
            adset[AdSet.Field.optimization_goal] = AdSet.OptimizationGoal.reach
            adset[AdSet.Field.daily_budget] = int(daily_budget * 100)
            adset[AdSet.Field.targeting] = {"geo_locations": {"countries": ["US"]}}
            adset[AdSet.Field.status] = AdSet.Status.active
            adset.remote_create(parent_id=fb_account.get_id_assured())

            # 3) Creative
            creative = AdCreative(api=api)
            creative[AdCreative.Field.name] = f"{ad_name} Creative"
            if asset_type == "video":
                creative[AdCreative.Field.object_story_spec] = {
                    "page_id": "",  # 需由调用方补充真实 page_id
                    "video_data": {
                        "video_id": video_id,
                        "title": headline,
                        "message": body,
                    },
                }
            else:
                creative[AdCreative.Field.object_story_spec] = {
                    "page_id": "",
                    "photo_data": {
                        "image_hash": image_hash,
                        "caption": headline,
                    },
                }
            creative.remote_create(parent_id=fb_account.get_id_assured())

            # 4) Ad
            ad = FBAd(api=api)
            ad[FBAd.Field.name] = ad_name
            ad[FBAd.Field.adset_id] = adset.get_id()
            ad[FBAd.Field.creative] = {"creative_id": creative.get_id()}
            ad[FBAd.Field.status] = FBAd.Status.active
            ad.remote_create(parent_id=fb_account.get_id_assured())

            return {
                "campaign_id": campaign.get_id(),
                "adset_id": adset.get_id(),
                "ad_id": ad.get_id(),
                "dev_mode": False,
                "error": None,
            }
        except Exception as e:
            logger.error(f"发布组合失败 (act={act}, idx={idx}): {str(e)}")
            return {
                "campaign_id": None,
                "adset_id": None,
                "ad_id": None,
                "dev_mode": False,
                "error": str(e),
            }

fb_client = FacebookClient()
