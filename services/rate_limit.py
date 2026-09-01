"""API速率限制管理器（升级：支持 account 与 BM 两个 scope）"""
from typing import Dict, Optional
from datetime import datetime, timedelta
from core.redis_client import redis_client
from core.logger import logger
import os

class RateLimitManager:
    """管理API速率限制
    支持按资源 scope 管理限流："account" 或 "bm"
    """

    def __init__(self, resource_id: str, scope: str = "account"):
        self.resource_id = resource_id
        self.scope = scope  # 'account' or 'bm'
        self.key_prefix = f"rate_limit:{scope}:{resource_id}"

        # 默认限额，可通过环境变量调整
        if scope == "bm":
            self.limits = {
                'minute': int(os.getenv('BM_RATE_MINUTE', 30)),
                'hour': int(os.getenv('BM_RATE_HOUR', 500)),
                'day': int(os.getenv('BM_RATE_DAY', 20000)),
            }
        else:
            self.limits = {
                'minute': int(os.getenv('ACCOUNT_RATE_MINUTE', 10)),
                'hour': int(os.getenv('ACCOUNT_RATE_HOUR', 200)),
                'day': int(os.getenv('ACCOUNT_RATE_DAY', 10000)),
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

            # 尝试原子自增并设置 ttl
            current = redis_client.incr(key)
            # 设置 ttl 仅当第一次创建（ttl == -1 或 ttl == None）
            try:
                if redis_client.ttl(key) == -1:
                    redis_client.expire(key, ttl)
            except Exception:
                # 部分 redis client 实现可能不支持 ttl 返回 -1
                pass

            return int(current)
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
                logger.info(f"Reset rate limit for {self.resource_id}:{window} (scope={self.scope})")
            else:
                # 重置所有窗口
                for w in ['minute', 'hour', 'day']:
                    key = f"{self.key_prefix}:{w}"
                    redis_client.delete(key)
                logger.info(f"Reset all rate limits for {self.resource_id} (scope={self.scope})")

            return True
        except Exception as e:
            logger.error(f"Failed to reset rate limit: {str(e)}")
            return False
