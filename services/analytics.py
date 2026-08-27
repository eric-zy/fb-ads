from typing import Dict, List, Tuple, Optional
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import AccountInsight, CampaignInsight, AdInsight, Campaign, Ad
from core.logger import logger
import numpy as np
from sklearn.ensemble import IsolationForest
import pandas as pd

class AnalyticsEngine:
    """数据分析引擎"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def calculate_metrics(self, spend: float, impressions: int, clicks: int,
                         conversions: int = 0) -> Dict[str, float]:
        """计算广告指标"""
        metrics = {
            'ctr': (clicks / impressions * 100) if impressions > 0 else 0,
            'cpc': (spend / clicks) if clicks > 0 else 0,
            'cpm': (spend / impressions * 1000) if impressions > 0 else 0,
            'conversion_rate': (conversions / clicks * 100) if clicks > 0 else 0,
        }
        return metrics
    
    def get_account_performance_trend(self, account_id: str, days: int = 30) -> pd.DataFrame:
        """获取账户性能趋势"""
        try:
            start_date = date.today() - timedelta(days=days)
            
            insights = self.db.query(AccountInsight).filter(
                AccountInsight.ad_account_id == account_id,
                AccountInsight.date >= start_date
            ).order_by(AccountInsight.date).all()
            
            if not insights:
                return pd.DataFrame()
            
            data = []
            for insight in insights:
                data.append({
                    'date': insight.date,
                    'spend': insight.spend,
                    'impressions': insight.impressions,
                    'clicks': insight.clicks,
                    'conversions': insight.conversions,
                    'ctr': insight.ctr,
                    'cpc': insight.cpc,
                    'cpm': insight.cpm,
                })
            
            df = pd.DataFrame(data)
            return df
            
        except Exception as e:
            logger.error(f"Failed to get performance trend: {str(e)}")
            return pd.DataFrame()
    
    def detect_spend_anomaly(self, account_id: str, window_days: int = 7) -> Tuple[float, bool]:
        """检测花费异常 (使用Isolation Forest)
        
        Returns:
            (异常得分, 是否异常)
        """
        try:
            df = self.get_account_performance_trend(account_id, window_days)
            
            if df.empty or len(df) < 3:
                return 0.0, False
            
            # 使用Isolation Forest进行异常检测
            X = df[['spend', 'ctr', 'cpc']].values
            clf = IsolationForest(contamination=0.1, random_state=42)
            predictions = clf.fit_predict(X)
            
            # 获取最后一天的异常分数
            last_score = clf.score_samples(X[-1:][0])[0]
            is_anomaly = predictions[-1] == -1
            
            return last_score, is_anomaly
            
        except Exception as e:
            logger.error(f"Failed to detect spend anomaly: {str(e)}")
            return 0.0, False
    
    def calculate_fraud_score(self, account_id: str, window_days: int = 7) -> float:
        """计算欺诈评分
        
        基于以下因素：
        1. 非正常花费模式 (80%)
        2. 低质量指标 (20%)
        """
        try:
            # 异常检测评分
            anomaly_score, is_anomaly = self.detect_spend_anomaly(account_id, window_days)
            
            # 规范化异常得分到0-1
            normalized_anomaly = max(0, min(1, (anomaly_score + 0.5)))
            
            # 获取低质量广告比例
            total_ads = self.db.query(Ad).join(
                Ad.ad_group
            ).join(
                Campaign
            ).filter(
                Campaign.ad_account_id == account_id
            ).count()
            
            low_quality_ads = self.db.query(Ad).join(
                Ad.ad_group
            ).join(
                Campaign
            ).filter(
                Campaign.ad_account_id == account_id,
                Ad.is_low_quality == True
            ).count()
            
            quality_ratio = (low_quality_ads / total_ads) if total_ads > 0 else 0
            
            # 综合评分
            fraud_score = (normalized_anomaly * 0.8) + (quality_ratio * 0.2)
            
            logger.info(f"Fraud score for {account_id}: {fraud_score} (anomaly: {normalized_anomaly}, quality: {quality_ratio})")
            return fraud_score
            
        except Exception as e:
            logger.error(f"Failed to calculate fraud score: {str(e)}")
            return 0.0
    
    def generate_daily_report(self, account_id: str, report_date: date) -> Dict:
        """生成日报告"""
        try:
            insight = self.db.query(AccountInsight).filter(
                AccountInsight.ad_account_id == account_id,
                AccountInsight.date == report_date
            ).first()
            
            if not insight:
                return {}
            
            # 计算与前一天的对比
            previous_date = report_date - timedelta(days=1)
            previous_insight = self.db.query(AccountInsight).filter(
                AccountInsight.ad_account_id == account_id,
                AccountInsight.date == previous_date
            ).first()
            
            report = {
                'date': str(report_date),
                'account_id': account_id,
                'metrics': {
                    'spend': insight.spend,
                    'impressions': insight.impressions,
                    'clicks': insight.clicks,
                    'conversions': insight.conversions,
                    'ctr': insight.ctr,
                    'cpc': insight.cpc,
                    'cpm': insight.cpm,
                    'roas': insight.roas,
                },
                'trend': {}
            }
            
            if previous_insight:
                report['trend'] = {
                    'spend_change': ((insight.spend - previous_insight.spend) / previous_insight.spend * 100) if previous_insight.spend > 0 else 0,
                    'clicks_change': ((insight.clicks - previous_insight.clicks) / previous_insight.clicks * 100) if previous_insight.clicks > 0 else 0,
                    'cpc_change': ((insight.cpc - previous_insight.cpc) / previous_insight.cpc * 100) if previous_insight.cpc > 0 else 0,
                }
            
            return report
            
        except Exception as e:
            logger.error(f"Failed to generate daily report: {str(e)}")
            return {}
    
    def generate_weekly_report(self, account_id: str, end_date: date = None) -> Dict:
        """生成周报告"""
        try:
            if end_date is None:
                end_date = date.today()
            
            start_date = end_date - timedelta(days=7)
            
            insights = self.db.query(AccountInsight).filter(
                AccountInsight.ad_account_id == account_id,
                AccountInsight.date >= start_date,
                AccountInsight.date <= end_date
            ).all()
            
            if not insights:
                return {}
            
            # 汇总指标
            total_spend = sum(i.spend for i in insights)
            total_impressions = sum(i.impressions for i in insights)
            total_clicks = sum(i.clicks for i in insights)
            total_conversions = sum(i.conversions for i in insights)
            
            metrics = self.calculate_metrics(
                total_spend, total_impressions, total_clicks, total_conversions
            )
            
            report = {
                'period': f"{start_date} to {end_date}",
                'account_id': account_id,
                'daily_count': len(insights),
                'total_metrics': {
                    'spend': total_spend,
                    'impressions': total_impressions,
                    'clicks': total_clicks,
                    'conversions': total_conversions,
                    **metrics
                },
                'daily_average': {
                    'spend': total_spend / len(insights),
                    'impressions': total_impressions / len(insights),
                    'clicks': total_clicks / len(insights),
                    'conversions': total_conversions / len(insights),
                }
            }
            
            return report
            
        except Exception as e:
            logger.error(f"Failed to generate weekly report: {str(e)}")
            return {}
