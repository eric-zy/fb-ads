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

fb_client = FacebookClient()
