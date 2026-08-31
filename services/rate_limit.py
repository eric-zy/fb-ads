"""API速率限制管理器"""
from typing import Dict, Optional
from datetime import datetime, timedelta
from core.redis_client import redis_client
from core.logger import logger

class RateLimitManager:
    """管理API速率限制"""
    
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.key_prefix = f"rate_limit:{account_id}"
        
        # Facebook API 限制
        self.limits = {
            'minute': 10,      # 每分钟10次
            'hour': 200,       # 每小时200次
            'day': 10000       # 每天10000次
        }
    
    def get_status(self) -> Dict:
        """获取当前速率限制状态
        
        Returns:
            各个时间窗口的使用情况
        """
        try:
            minute_key = f"{self.key_prefix}:minute"
            hour_key = f"{self.key_prefix}:hour"
            day_key = f"{self.key_prefix}:day"
            
            minute_count = int(redis_client.get(minute_key, 0) or 0)
            hour_count = int(redis_client.get(hour_key, 0) or 0)
            day_count = int(redis_client.get(day_key, 0) or 0)
            
            return {
                'minute': {
                    'used': minute_count,
                    'limit': self.limits['minute'],
                    'remaining': max(0, self.limits['minute'] - minute_count)
                },
                'hour': {
                    'used': hour_count,
                    'limit': self.limits['hour'],
                    'remaining': max(0, self.limits['hour'] - hour_count)
                },
                'day': {
                    'used': day_count,
                    'limit': self.limits['day'],
                    'remaining': max(0, self.limits['day'] - day_count)
                }
            }
        except Exception as e:
            logger.error(f"Failed to get rate limit status: {str(e)}")
            return {}
    
    def check_limit(self, window: str = 'hour') -> bool:
        """检查是否超过限制
        
        Args:
            window: 时间窗口 (minute, hour, day)
        
        Returns:
            是否在限制内
        """
        try:
            key = f"{self.key_prefix}:{window}"
            count = int(redis_client.get(key, 0) or 0)
            limit = self.limits.get(window, 0)

            return count < limit
        except Exception as e:
            logger.error(f"Failed to check rate limit: {str(e)}")
            return True  # 出错时允许请求
    
    def increment(self, window: str = 'hour') -> int:
        """增加计数器
        
        Args:
            window: 时间窗口
        
        Returns:
            新的计数值
        """
        try:
            key = f"{self.key_prefix}:{window}"
            
            # 设置过期时间
            if window == 'minute':
                ttl = 60
            elif window == 'hour':
                ttl = 3600
            else:  # day
                ttl = 86400
            
            return redis_client.incr(key, 1, ttl=ttl)
        except Exception as e:
            logger.error(f"Failed to increment rate limit: {str(e)}")
            return 0
    
    def reset(self, window: Optional[str] = None) -> bool:
        """重置计数器
        
        Args:
            window: 时间窗口，None表示全部
        
        Returns:
            是否重置成功
        """
        try:
            if window:
                key = f"{self.key_prefix}:{window}"
                redis_client.delete(key)
                logger.info(f"Reset rate limit for {self.account_id}:{window}")
            else:
                # 重置所有窗口
                for w in ['minute', 'hour', 'day']:
                    key = f"{self.key_prefix}:{w}"
                    redis_client.delete(key)
                logger.info(f"Reset all rate limits for {self.account_id}")
            
            return True
        except Exception as e:
            logger.error(f"Failed to reset rate limit: {str(e)}")
            return False
