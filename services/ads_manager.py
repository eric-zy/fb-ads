from typing import Optional, List, Dict, Tuple
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import Campaign, AdGroup, Ad, CampaignStatus
from services.fb_client import fb_client
from core.logger import logger
from core.redis_client import redis_client
import json

class AdsManager:
    """广告管理服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def sync_campaigns(self, account_id: str) -> Tuple[int, int]:
        """同步系列数据
        
        Returns:
            (新增数量, 更新数量)
        """
        try:
            campaigns = fb_client.get_campaigns(account_id)
            created_count = 0
            updated_count = 0
            
            for campaign_data in campaigns:
                campaign_id = campaign_data.get('id')
                
                # 查询现有记录
                existing = self.db.query(Campaign).filter_by(campaign_id=campaign_id).first()
                
                if existing:
                    # 更新
                    existing.name = campaign_data.get('name')
                    existing.status = campaign_data.get('status', 'ACTIVE')
                    existing.objective = campaign_data.get('objective')
                    existing.updated_at = datetime.utcnow()
                    updated_count += 1
                else:
                    # 创建新记录
                    new_campaign = Campaign(
                        id=f"{account_id}_{campaign_id}",
                        campaign_id=campaign_id,
                        ad_account_id=account_id,
                        name=campaign_data.get('name'),
                        status=campaign_data.get('status', 'ACTIVE'),
                        objective=campaign_data.get('objective'),
                        daily_budget=campaign_data.get('daily_budget'),
                        budget=campaign_data.get('lifetime_budget')
                    )
                    self.db.add(new_campaign)
                    created_count += 1
            
            self.db.commit()
            logger.info(f"Synced campaigns: created={created_count}, updated={updated_count}")
            return created_count, updated_count
            
        except Exception as e:
            logger.error(f"Failed to sync campaigns: {str(e)}")
            self.db.rollback()
            return 0, 0
    
    def get_campaign_performance(self, campaign_id: str, 
                                 date_start: date, date_stop: date) -> Optional[Dict]:
        """获取系列性能数据"""
        try:
            # 尝试从缓存获取
            cache_key = f"campaign_perf:{campaign_id}:{date_start}:{date_stop}"
            cached = redis_client.get_json(cache_key)
            if cached:
                return cached
            
            # 从Facebook API获取
            insights = fb_client.get_insights(
                account_id=self.db.query(Campaign).filter_by(campaign_id=campaign_id).first().ad_account_id,
                date_start=str(date_start),
                date_stop=str(date_stop),
                level='campaign',
                params={'campaign_ids': [campaign_id]}
            )
            
            if insights:
                result = insights[0]
                # 缓存24小时
                redis_client.set(cache_key, result, ex=86400)
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get campaign performance: {str(e)}")
            return None
    
    def pause_low_performance_campaigns(self, account_id: str, 
                                       ctr_threshold: float = 0.02,
                                       cpc_threshold: float = 5.0) -> int:
        """暂停低性能系列
        
        Returns:
            暂停的系列数量
        """
        try:
            campaigns = self.db.query(Campaign).filter_by(
                ad_account_id=account_id,
                status=CampaignStatus.ACTIVE
            ).all()
            
            paused_count = 0
            yesterday = date.today() - timedelta(days=1)
            
            for campaign in campaigns:
                perf = self.get_campaign_performance(
                    campaign.campaign_id,
                    yesterday,
                    yesterday
                )
                
                if perf:
                    ctr = float(perf.get('ctr', 0))
                    cpc = float(perf.get('cpc', 0))
                    
                    # 如果CTR过低或CPC过高
                    if (ctr < ctr_threshold and ctr > 0) or (cpc > cpc_threshold and cpc > 0):
                        if fb_client.pause_campaign(campaign.campaign_id):
                            campaign.status = CampaignStatus.PAUSED
                            paused_count += 1
            
            self.db.commit()
            logger.info(f"Paused {paused_count} low-performance campaigns")
            return paused_count
            
        except Exception as e:
            logger.error(f"Failed to pause low-performance campaigns: {str(e)}")
            self.db.rollback()
            return 0
    
    def get_account_spend_today(self, account_id: str) -> float:
        """获取账户今日花费"""
        try:
            today = date.today()
            insights = fb_client.get_insights(
                account_id=account_id,
                date_start=str(today),
                date_stop=str(today),
                level='account'
            )
            
            if insights:
                return float(insights[0].get('spend', 0))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Failed to get account spend: {str(e)}")
            return 0.0
