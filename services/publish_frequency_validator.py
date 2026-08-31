"""发布频次验证器 - 防止账户因过度操作被禁用"""
from datetime import datetime, timedelta
from typing import Dict, Tuple, List, Optional
from sqlalchemy import or_
from sqlalchemy.orm import Session
from core.logger import logger
from models import Campaign, AdAccount, SystemStatus

class PublishFrequencyValidator:
    """验证账户的发布频次是否安全"""
    
    def __init__(self, db: Session):
        self.db = db
        # 建议的发布间隔（秒）
        self.safe_intervals = {
            'very_high_risk': 600,      # 10分钟
            'high_risk': 300,           # 5分钟
            'medium_risk': 120,         # 2分钟
            'low_risk': 60,             # 1分钟
            'safe': 30                  # 30秒
        }
    
    def _resolve_ad_account_ids(self, account_id: str) -> List[str]:
        """把账户标识解析为可用于 Campaign.ad_account_id 过滤的取值集合。

        历史数据存在两种写法：
          - 存 Meta 账户号（act_xxx，即 ad_accounts.account_id）
          - 存内部主键（ad_accounts.id）
        这里同时返回两者，保证不同来源的历史数据都能被统计到。
        """
        candidates = {account_id}

        account = (
            self.db.query(AdAccount)
            .filter(
                or_(AdAccount.account_id == account_id, AdAccount.id == account_id)
            )
            .first()
        )
        if account:
            candidates.add(account.id)
            if account.account_id:
                candidates.add(account.account_id)

        return [c for c in candidates if c]

    def check_campaign_publish_frequency(self, account_id: str, hours: int = 24) -> Dict:
        """检查账户在指定时间内的系列创建频次
        
        Args:
            account_id: 账户ID（Meta 账户号或内部主键皆可）
            hours: 检查时间窗口（小时）
        
        Returns:
            频次检查报告
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # 查询在时间窗口内创建的系列
            campaigns = self.db.query(Campaign).filter(
                Campaign.ad_account_id.in_(self._resolve_ad_account_ids(account_id)),
                Campaign.created_at >= cutoff_time
            ).all()
            
            campaign_count = len(campaigns)
            
            # 计算频次
            campaigns_per_hour = campaign_count / max(hours, 1)
            
            # 判断风险等级
            if campaigns_per_hour > 5:
                status = 'critical'
                risk_level = 'very_high_risk'
            elif campaigns_per_hour > 3:
                status = 'high_risk'
                risk_level = 'high_risk'
            elif campaigns_per_hour > 1:
                status = 'warning'
                risk_level = 'medium_risk'
            elif campaigns_per_hour > 0.5:
                status = 'medium'
                risk_level = 'low_risk'
            else:
                status = 'safe'
                risk_level = 'safe'
            
            return {
                'status': status,
                'risk_level': risk_level,
                'campaigns_created': campaign_count,
                'campaigns_per_hour': round(campaigns_per_hour, 2),
                'time_window_hours': hours,
                'recommended_interval': self.safe_intervals[risk_level]
            }
        except Exception as e:
            logger.error(f"Failed to check campaign publish frequency: {str(e)}")
            return {'status': 'error', 'error': str(e)}
    
    def validate_account_health(self, account_id: str) -> Tuple[bool, Dict]:
        """验证账户的整体健康状况
        
        Args:
            account_id: 账户ID
        
        Returns:
            (是否健康, 健康报告)
        """
        try:
            account = self.db.query(AdAccount).filter(
                or_(AdAccount.account_id == account_id, AdAccount.id == account_id)
            ).first()
            
            if not account:
                return False, {'status': 'not_found', 'message': 'Account not found'}

            # 系统侧状态（system_status）决定是否允许参与投放；
            # Meta 侧状态在 account_status / effective_status，同步维护，此处不参与健康判定
            status_value = account.system_status
            is_active = account.system_status == SystemStatus.ACTIVE.value

            # 检查系统侧状态
            if not is_active:
                return False, {
                    'status': status_value,
                    'is_active': is_active,
                    'system_status_reason': account.system_status_reason,
                    'message': 'Account is frozen or inactive'
                }
            
            # 检查发布频次
            freq_report = self.check_campaign_publish_frequency(account_id, hours=24)
            
            is_healthy = freq_report['status'] in ['safe', 'medium']
            
            return is_healthy, {
                'status': status_value,
                'is_active': is_active,
                'system_status_reason': account.system_status_reason,
                'publish_frequency': freq_report,
                'message': 'Account is healthy' if is_healthy else 'Account has issues'
            }
        except Exception as e:
            logger.error(f"Failed to validate account health: {str(e)}")
            return False, {'status': 'error', 'error': str(e)}
    
    def recommend_action(self, account_id: str) -> Dict:
        """基于账户状态推荐行动
        
        Args:
            account_id: 账户ID
        
        Returns:
            推荐行动列表
        """
        try:
            is_healthy, health_report = self.validate_account_health(account_id)
            
            recommendations = []
            
            if not is_healthy:
                if health_report.get('status') == SystemStatus.DISABLED.value:
                    recommendations.append({
                        'priority': 'critical',
                        'type': 'account_frozen',
                        'message': '账户已被冻结，需要立即处理'
                    })
                
                freq_status = health_report.get('publish_frequency', {}).get('status')
                if freq_status in ['critical', 'high_risk']:
                    recommendations.append({
                        'priority': 'high',
                        'type': 'reduce_publish_frequency',
                        'message': f'发布频次过高，建议降低创建系列的频率'
                    })
                elif freq_status == 'warning':
                    recommendations.append({
                        'priority': 'medium',
                        'type': 'monitor_frequency',
                        'message': '发布频次偏高，建议监控'
                    })
            else:
                recommendations.append({
                    'priority': 'low',
                    'type': 'continue_monitoring',
                    'message': '账户运行正常，继续监控'
                })
            
            return {
                'account_id': account_id,
                'overall_status': 'healthy' if is_healthy else 'unhealthy',
                'actions': recommendations,
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to recommend actions: {str(e)}")
            return {'status': 'error', 'error': str(e)}
    
    def get_safe_publish_interval(self, account_id: str) -> Dict:
        """获取安全的发布间隔时间
        
        Args:
            account_id: 账户ID
        
        Returns:
            安全间隔建议
        """
        try:
            freq_report = self.check_campaign_publish_frequency(account_id, hours=24)
            
            interval_seconds = freq_report.get('recommended_interval', 60)
            risk_level = freq_report.get('risk_level', 'unknown')
            
            messages = {
                'very_high_risk': '账户风险极高，建议每10分钟发布一次',
                'high_risk': '账户风险较高，建议每5分钟发布一次',
                'medium_risk': '账户风险中等，建议每2分钟发布一次',
                'low_risk': '账户风险较低，建议每1分钟发布一次',
                'safe': '账户风险低，建议每30秒发布一次'
            }
            
            return {
                'account_id': account_id,
                'recommended_interval_seconds': interval_seconds,
                'risk_level': risk_level,
                'message': messages.get(risk_level, '未知风险级别'),
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get safe publish interval: {str(e)}")
            return {'status': 'error', 'error': str(e)}
