"""Meta API 服务层（设计文档第 19 节 / 原则六：SDK 隔离）

业务代码不应直接 import facebook_business，统一通过本包访问：

    Application
          ↓
    MetaAdsService
          ↓
    facebook_business
          ↓
    Meta Marketing API
"""
from services.meta.errors import MetaApiError, classify, classify_facebook_error
from services.meta.client import MetaClient
from services.meta.service import MetaAdsService
from services.meta.ad_account_service import AdAccountService
from services.meta.business_service import BusinessService
from services.meta.sync_service import MetaSyncService

__all__ = [
    "MetaApiError",
    "classify",
    "classify_facebook_error",
    "MetaClient",
    "MetaAdsService",
    "AdAccountService",
    "BusinessService",
    "MetaSyncService",
]
