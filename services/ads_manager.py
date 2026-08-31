from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import Campaign, AdGroup, Ad, CampaignStatus, PublishTask, PublishedAd, CreativeAsset, AdAccount
from services.fb_client import fb_client
from services.credential_service import CredentialError, CredentialService
from config.settings import settings
from core.logger import logger
from core.money import to_major, to_minor
from core.redis_client import redis_client
import json


def _minor_int(value) -> Optional[int]:
    """Meta 的 budget 字段返回最小货币单位字符串（"10000" = $100.00）"""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


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
                    existing.daily_budget = _minor_int(campaign_data.get('daily_budget'))
                    existing.budget = _minor_int(campaign_data.get('lifetime_budget'))
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
                        daily_budget=_minor_int(campaign_data.get('daily_budget')),
                        budget=_minor_int(campaign_data.get('lifetime_budget'))
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
    
    def get_account_spend_today(self, account_id: str) -> int:
        """获取账户今日花费（**最小货币单位**，与库内金额字段一致）

        Meta insights 的 `spend` 返回主单位字符串（如 "10.50"），
        此处统一换算为最小货币单位，便于与 `daily_spend_limit` 等字段直接比较。
        """
        try:
            today = date.today()
            insights = fb_client.get_insights(
                account_id=account_id,
                date_start=str(today),
                date_stop=str(today),
                level='account'
            )
            
            if insights:
                return to_minor(float(insights[0].get('spend', 0) or 0))
            
            return 0
            
        except Exception as e:
            logger.error(f"Failed to get account spend: {str(e)}")
            return 0

    def publish_batch(
        self,
        *,
        name: str,
        account_ids: List[str],
        asset_ids: List[str],
        copies: List[Dict[str, str]],
        objective: str = "OUTCOME_SALES",
        daily_budget_minor: int = 5000,
        name_prefix: str = "Batch",
    ) -> Dict[str, Any]:
        """批量发布：账户 × 素材 × 文案 的组合逐一创建 Campaign+AdSet+Ad。

        每个组合调用 fb_client.publish_combo（真实 FB 或开发降级）。
        结果落库到 PublishTask / PublishedAd。

        Args:
            daily_budget_minor: 日预算，**最小货币单位**（默认 5000 = $50.00）
        """
        assets = []
        if asset_ids:
            assets = self.db.query(CreativeAsset).filter(CreativeAsset.id.in_(asset_ids)).all()
        if not assets:
            # 允许纯文案（无素材）发布
            assets = [None]

        accounts = self.db.query(AdAccount).filter(AdAccount.id.in_(account_ids)).all()

        task = PublishTask(
            id=__import__("uuid").uuid4().hex,
            name=name,
            account_ids=__import__("json").dumps(account_ids),
            asset_ids=__import__("json").dumps(asset_ids),
            copies=__import__("json").dumps(copies),
            objective=objective,
            daily_budget=daily_budget_minor,
            name_prefix=name_prefix,
            total=0,
            success=0,
            failed=0,
            status="running",
        )
        self.db.add(task)
        self.db.commit()

        total = 0
        success = 0
        failed = 0
        dev_mode = False

        credential_service = CredentialService(self.db)

        for acc in accounts:
            # Token 由凭据服务按所属 BM 解析（加密凭据优先，最后兜底全局配置）
            try:
                access_token, _ = credential_service.resolve_token_for_meta(acc.business_id)
            except CredentialError as e:
                logger.error(f"[AdsManager] 账户 {acc.account_id} 凭据不可用，跳过: {e}")
                continue

            for asset in assets:
                asset_type = asset.asset_type if asset else "none"
                image_hash = asset.fb_hash if (asset and asset.asset_type == "image") else None
                video_id = asset.fb_video_id if (asset and asset.asset_type == "video") else None
                for ci, copy in enumerate(copies):
                    total += 1
                    res = fb_client.publish_combo(
                        account_id=acc.account_id,
                        access_token=access_token,
                        name_prefix=name_prefix,
                        objective=objective,
                        # fb_client 处于 SDK 边界，接收主单位（元）并在内部 ×100
                        daily_budget=to_major(daily_budget_minor),
                        asset_type=asset_type if asset else "image",
                        image_hash=image_hash,
                        video_id=video_id,
                        headline=copy.get("headline", ""),
                        body=copy.get("body", ""),
                        idx=total,
                    )
                    item = PublishedAd(
                        id=__import__("uuid").uuid4().hex,
                        task_id=task.id,
                        account_id=acc.account_id,
                        asset_id=asset.id if asset else None,
                        asset_type=asset_type if asset else None,
                        headline=copy.get("headline", ""),
                        body=copy.get("body", ""),
                        fb_campaign_id=res.get("campaign_id"),
                        fb_adset_id=res.get("adset_id"),
                        fb_ad_id=res.get("ad_id"),
                        status="failed" if res.get("error") else "success",
                        error=res.get("error"),
                    )
                    self.db.add(item)
                    if res.get("dev_mode"):
                        dev_mode = True
                    if res.get("error"):
                        failed += 1
                    else:
                        success += 1

        task.total = total
        task.success = success
        task.failed = failed
        # 修正：原写法在「全部失败」(success=0 且 failed>0) 时会误判为 done
        if failed == 0:
            task.status = "done"
        elif success == 0:
            task.status = "failed"
        else:
            task.status = "partial"
        task.dev_mode = dev_mode
        self.db.commit()
        self.db.refresh(task)

        return {
            "task_id": task.id,
            "total": total,
            "success": success,
            "failed": failed,
            "dev_mode": dev_mode,
            "items": [i.to_dict() for i in task.items],
        }
