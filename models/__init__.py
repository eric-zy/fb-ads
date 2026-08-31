from models.ad_account import AdAccount, AccountStatus, SystemStatus
from models.meta_account import MetaAccount, BusinessStatus, SyncStatus
from models.creative_asset import CreativeAsset
from models.campaign import Campaign, CampaignStatus
from models.ad_group import AdGroup
from models.ad import Ad
from models.publish_task import PublishTask, PublishedAd
from models.insights import AccountInsight, CampaignInsight, AdInsight
from models.risk_control import RiskEvent, RiskLevel, RiskEventType, RiskRule
from models.user import User, UserAccount

# ---- 对齐设计文档新增的核心模型 ----
# Campaign Template：系统最核心业务对象（设计文档第 3.1 / 10 节）
from models.template import CampaignTemplate
# Template → 多账户部署的实例映射（设计文档第 12 / 13 / 14 节）
from models.instance import CampaignInstance, AdSetInstance, AdInstance
# 加密凭据（设计文档第 9 节 / Meta 账号管理 V1 §4）
from models.credential import Credential
# Job Center（设计文档第 17 节）
from models.job import CampaignJob, CampaignJobItem
# 审计日志（设计文档第 41.3 节）
from models.audit_log import AuditLog
# Meta 同步日志（Meta 账号管理 V1 §10）—— 同步结果，与操作审计分开记录
from models.sync_log import MetaSyncLog, SyncType, SyncLogStatus

__all__ = [
    'AdAccount',
    'AccountStatus',   # 遗留枚举，已被 SystemStatus 取代，仅为兼容保留
    'SystemStatus',
    'MetaAccount',
    'BusinessStatus',
    'SyncStatus',
    'Campaign',
    'CampaignStatus',
    'AdGroup',
    'Ad',
    'CreativeAsset',
    'PublishTask',
    'PublishedAd',
    'AccountInsight',
    'CampaignInsight',
    'AdInsight',
    'RiskEvent',
    'RiskLevel',
    'RiskEventType',
    'RiskRule',
    'User',
    'UserAccount',
    # 新增
    'CampaignTemplate',
    'CampaignInstance',
    'AdSetInstance',
    'AdInstance',
    'Credential',
    'CampaignJob',
    'CampaignJobItem',
    'AuditLog',
    'MetaSyncLog',
    'SyncType',
    'SyncLogStatus',
]
