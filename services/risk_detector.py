from typing import List, Dict, Optional, Tuple
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import RiskEvent, RiskLevel, RiskEventType, AdAccount, Campaign, Ad, SystemStatus
from services.fb_client import fb_client
from services.ads_manager import AdsManager
from config.settings import settings
from core.logger import logger
from core.money import to_minor
import json

class RiskDetector:
    """风控检测服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.ads_manager = AdsManager(db)
    
    def check_daily_spend_anomaly(self, account_id: str) -> Optional[Tuple[int, int]]:
        """检查每日花费异常

        金额单位统一为**最小货币单位**（与 AdAccount.daily_spend_limit 一致）。

        Returns:
            (今日花费, 日限额) 或 None
        """
        try:
            account = self.db.query(AdAccount).filter_by(account_id=account_id).first()
            if not account:
                return None

            today_spend = self.ads_manager.get_account_spend_today(account_id)
            daily_limit = account.daily_spend_limit or 0

            # 如果超过日预算80%
            if daily_limit > 0 and today_spend > daily_limit * 0.8:
                logger.warning(f"Daily spend anomaly detected: {today_spend} > {daily_limit * 0.8}")
                return today_spend, daily_limit
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check daily spend anomaly: {str(e)}")
            return None
    
    def check_quality_score_anomaly(self, account_id: str) -> List[str]:
        """检查广告质量评分异常
        
        Returns:
            低质量的广告ID列表
        """
        try:
            campaigns = self.db.query(Campaign).filter_by(ad_account_id=account_id).all()
            low_quality_ads = []
            
            for campaign in campaigns:
                ads = self.db.query(Ad).filter(
                    Ad.ad_group.has(campaign_id=campaign.id)
                ).all()
                
                for ad in ads:
                    # 如果质量分低于50分（Facebook通常是1-10分，这里我们假设转换为0-100）
                    if ad.quality_score > 0 and ad.quality_score < 50:
                        ad.is_low_quality = True
                        low_quality_ads.append(ad.ad_id)
            
            if low_quality_ads:
                self.db.commit()
                logger.warning(f"Found {len(low_quality_ads)} low-quality ads")
            
            return low_quality_ads
            
        except Exception as e:
            logger.error(f"Failed to check quality score anomaly: {str(e)}")
            return []
    
    def detect_fraud_pattern(self, account_id: str, window_days: int = 7) -> float:
        """检测欺诈模式 (使用简单的异常检测算法)
        
        Returns:
            欺诈评分 (0-1.0)
        """
        try:
            from services.analytics import AnalyticsEngine
            
            analytics = AnalyticsEngine(self.db)
            fraud_score = analytics.calculate_fraud_score(account_id, window_days)
            
            if fraud_score > settings.RISK_FRAUD_SCORE_THRESHOLD:
                logger.warning(f"High fraud risk detected: score={fraud_score}")
            
            return fraud_score
            
        except Exception as e:
            logger.error(f"Failed to detect fraud pattern: {str(e)}")
            return 0.0
    
    def create_risk_event(self, account_id: str, event_type: RiskEventType,
                         risk_level: RiskLevel, title: str, description: str,
                         related_campaign_id: Optional[str] = None,
                         related_ad_id: Optional[str] = None,
                         auto_action: Optional[str] = None,
                         requires_manual_review: bool = False) -> Optional[RiskEvent]:
        """创建风险事件记录"""
        try:
            event = RiskEvent(
                id=f"risk_{account_id}_{datetime.utcnow().timestamp()}",
                ad_account_id=account_id,
                event_type=event_type,
                risk_level=risk_level,
                title=title,
                description=description,
                related_campaign_id=related_campaign_id,
                related_ad_id=related_ad_id,
                auto_action_taken=auto_action,
                requires_manual_review=requires_manual_review
            )
            
            self.db.add(event)
            self.db.commit()
            logger.info(f"Risk event created: {event.id}")
            return event
            
        except Exception as e:
            logger.error(f"Failed to create risk event: {str(e)}")
            self.db.rollback()
            return None
    
    def freeze_account(self, account_id: str, reason: str, days: int = 3) -> bool:
        """冻结账户"""
        try:
            account = self.db.query(AdAccount).filter_by(account_id=account_id).first()
            if not account:
                return False
            
            # 冻结 = 系统侧禁止参与批量投放（Meta 状态由同步维护，不在此改写）
            account.system_status = SystemStatus.DISABLED.value
            account.system_status_reason = reason
            account.system_status_at = datetime.utcnow()

            self.db.commit()
            logger.warning(f"Account {account_id} frozen: {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to freeze account: {str(e)}")
            self.db.rollback()
            return False
    
    def execute_risk_actions(self, account_id: str) -> Dict[str, int]:
        """执行风险缓解行动
        
        Returns:
            行动统计 {"campaigns_paused": int, "accounts_frozen": int}
        """
        result = {"campaigns_paused": 0, "accounts_frozen": 0}
        
        try:
            # 检查日花费异常
            spend_anomaly = self.check_daily_spend_anomaly(account_id)
            if spend_anomaly:
                today_spend, daily_limit = spend_anomaly
                paused = self.ads_manager.pause_low_performance_campaigns(account_id)
                result["campaigns_paused"] += paused
                
                self.create_risk_event(
                    account_id=account_id,
                    event_type=RiskEventType.UNUSUAL_SPEND,
                    risk_level=RiskLevel.HIGH,
                    title="异常花费检测",
                    description=f"今日花费 {today_spend} 超过预算限额 {daily_limit}",
                    auto_action=f"Paused {paused} campaigns",
                    requires_manual_review=True
                )
            
            # 检查欺诈模式
            fraud_score = self.detect_fraud_pattern(account_id)
            if fraud_score > settings.RISK_FRAUD_SCORE_THRESHOLD:
                self.freeze_account(
                    account_id,
                    f"High fraud risk detected (score: {fraud_score})",
                    settings.RISK_ACCOUNT_FREEZE_DAYS
                )
                result["accounts_frozen"] += 1
                
                self.create_risk_event(
                    account_id=account_id,
                    event_type=RiskEventType.HIGH_FRAUD,
                    risk_level=RiskLevel.CRITICAL,
                    title="高欺诈风险",
                    description=f"检测到高欺诈风险，评分：{fraud_score}",
                    auto_action="Account frozen",
                    requires_manual_review=True
                )
            
            logger.info(f"Risk actions executed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute risk actions: {str(e)}")
            return result
