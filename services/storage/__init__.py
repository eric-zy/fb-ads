"""Object storage adapters."""

from services.storage.aliyun_oss import AliyunOSSStorage, StorageError

__all__ = ["AliyunOSSStorage", "StorageError"]
