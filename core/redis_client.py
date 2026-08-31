import redis
from typing import Optional, Any
from config.settings import settings
from core.logger import logger
import json

class RedisClient:
    """Redis客户端封装"""
    
    def __init__(self):
        self.redis_client = redis.from_url(
            settings.redis_url,
            socket_timeout=settings.REDIS_TIMEOUT,
            socket_connect_timeout=settings.REDIS_TIMEOUT,
            decode_responses=True
        )
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取值"""
        try:
            value = self.redis_client.get(key)
            return value if value is not None else default
        except Exception as e:
            logger.error(f"Redis get error: {str(e)}")
            return default
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """设置值"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.redis_client.set(key, value, ex=ex)
            return True
        except Exception as e:
            logger.error(f"Redis set error: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        """删除key"""
        try:
            self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Redis delete error: {str(e)}")
            return False
    
    def exists(self, key: str) -> bool:
        """检查key是否存在"""
        try:
            return self.redis_client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists error: {str(e)}")
            return False
    
    def incr(self, key: str, amount: int = 1, ttl: Optional[int] = None) -> int:
        """自增计数

        Args:
            amount: 自增步长
            ttl: 可选过期秒数。仅在 key 首次创建时设置（nx=True），
                 保证限流窗口不会因重复设置而被无限延长。
        """
        try:
            pipe = self.redis_client.pipeline()
            pipe.incrby(key, amount)
            if ttl:
                pipe.expire(key, ttl, nx=True)
            result = pipe.execute()
            return result[0]
        except Exception as e:
            logger.error(f"Redis incr error: {str(e)}")
            return 0
    
    def lpush(self, key: str, value: Any) -> int:
        """左侧入栈"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            return self.redis_client.lpush(key, value)
        except Exception as e:
            logger.error(f"Redis lpush error: {str(e)}")
            return 0
    
    def lpop(self, key: str) -> Optional[str]:
        """左侧出栈"""
        try:
            return self.redis_client.lpop(key)
        except Exception as e:
            logger.error(f"Redis lpop error: {str(e)}")
            return None
    
    def get_json(self, key: str) -> Optional[dict]:
        """获取JSON值"""
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Redis get_json error: {str(e)}")
            return None
    
    def close(self):
        """关闭连接"""
        try:
            self.redis_client.close()
        except Exception as e:
            logger.error(f"Redis close error: {str(e)}")

redis_client = RedisClient()