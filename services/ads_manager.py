from typing import Optional, Dict, Tuple
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import (
    AccountInsight,
    CampaignInsight,
    AdSetInsight,
    Ad,
    AdAccount,
    AdGroup,
    Campaign,
    CampaignStatus,
)
from services.ad_account_resolver import resolve_ad_account
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient, FBConnectorError
from config.settings import settings
from core.logger import logger
from core.money import to_major, to_minor
from core.redis_client import redis_client
import hashlib


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

    def _account_insights(self, account: AdAccount, start_date: str, end_date: str, level: str):
        """使用账户绑定凭据访问 Meta，禁止回退到全局单例客户端。"""
        ref = CredentialResolver(self.db).for_account(account.id)
        return FBConnectorClient().get_insights(
            account.account_id, ref.credential_id,
            level=level, since=start_date, until=end_date,
        ).get("items", [])
    
    def sync_campaigns(self, account_id: str) -> Tuple[int, int]:
        """同步系列数据

        Args:
            account_id: 广告账户内部主键

        Returns:
            (新增数量, 更新数量)
        """
        # 归一到主键：调 Meta API 要用 act_xxx，写外键要用主键，
        # 混用会让 Campaign.ad_account_id 存进 act_xxx 而关联不上账户。
        account = resolve_ad_account(self.db, account_id)
        if not account:
            logger.warning(f"[AdsManager] 账户不存在，跳过系列同步: {account_id}")
            return 0, 0

        try:
            ref = CredentialResolver(self.db).for_account(account.id)
            campaigns = FBConnectorClient().list_campaigns(
                account.account_id, ref.credential_id
            ).get("campaigns", [])
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
                    # 内部主键必须保持在 VARCHAR(50) 内；Meta Campaign ID
                    # 与账户主键拼接后可能超过 50 字符，使用稳定哈希避免
                    # 重复同步产生重复记录，同时不改变外部 campaign_id。
                    internal_id = hashlib.sha256(
                        f"{account.id}:{campaign_id}".encode("utf-8")
                    ).hexdigest()[:32]
                    new_campaign = Campaign(
                        id=internal_id,
                        campaign_id=campaign_id,
                        ad_account_id=account.id,  # 外键存主键
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
            campaign = self.db.query(Campaign).filter_by(campaign_id=campaign_id).first()
            if not campaign:
                return None
            account = resolve_ad_account(self.db, campaign.ad_account_id)
            if not account:
                return None
            insights = self._account_insights(account, str(date_start), str(date_stop), 'campaign')
            insights = [row for row in insights if row.get('campaign_id') == campaign_id]
            
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
                        account = resolve_ad_account(self.db, campaign.ad_account_id)
                        if account:
                            ref = CredentialResolver(self.db).for_account(account.id)
                            FBConnectorClient().pause_campaign(
                                campaign.campaign_id,
                                ref.credential_id,
                                idempotency_key=f"pause:{campaign.campaign_id}:{yesterday}",
                            )
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

        Args:
            account_id: 广告账户内部主键
        """
        account = resolve_ad_account(self.db, account_id)
        if not account:
            logger.warning(f"[AdsManager] 账户不存在: {account_id}")
            return 0

        try:
            today = date.today()
            insights = self._account_insights(account, str(today), str(today), 'account')
            
            if insights:
                return to_minor(float(insights[0].get('spend', 0) or 0))
            
            return 0
            
        except Exception as e:
            logger.error(f"Failed to get account spend: {str(e)}")
            return 0

    def fetch_insights(self, account_id: str, start_date: str, end_date: str) -> int:
        """拉取账户洞察并落库到 account_insights（Celery 定时任务入口）

        按天写入，同一 (账户, 日期) 重复拉取时做 upsert，保证任务可重跑。

        Args:
            account_id: 广告账户内部主键
            start_date: 起始日期 YYYY-MM-DD
            end_date:   结束日期 YYYY-MM-DD（含）

        Returns:
            写入/更新的洞察条数
        """
        account = resolve_ad_account(self.db, account_id)
        if not account:
            logger.warning(f"[AdsManager] 账户不存在，跳过洞察拉取: {account_id}")
            return 0

        try:
            insights = self._account_insights(account, start_date, end_date, "account")
        except Exception as e:
            logger.error(f"[AdsManager] 拉取洞察失败 {account.account_id}: {e}")
            return 0

        if not insights:
            return 0

        count = 0
        for row in insights:
            insight_date = self._parse_date(row.get('date_start') or start_date)
            if not insight_date:
                continue

            spend = to_minor(float(row.get('spend', 0) or 0))
            impressions = int(row.get('impressions', 0) or 0)
            clicks = int(row.get('clicks', 0) or 0)
            action_metrics = self._parse_action_metrics(row.get('actions'), row.get('action_values'))

            existing = (
                self.db.query(AccountInsight)
                .filter(
                    AccountInsight.ad_account_id == account.id,
                    AccountInsight.date == insight_date,
                )
                .first()
            )
            if existing:
                target = existing
            else:
                target = AccountInsight(
                    id=f"ins_{account.id}_{insight_date}",
                    ad_account_id=account.id,
                    date=insight_date,
                )
                self.db.add(target)

            target.spend = spend
            target.impressions = impressions
            target.clicks = clicks
            target.conversions = action_metrics["conversions"]
            target.link_clicks = action_metrics["link_clicks"]
            target.landing_page_views = action_metrics["landing_page_views"]
            target.leads = action_metrics["leads"]
            target.purchases = action_metrics["purchases"]
            target.complete_registrations = action_metrics["complete_registrations"]
            target.conversion_value = to_minor(action_metrics["conversion_value"])
            target.actions = row.get("actions") or []
            target.action_values = row.get("action_values") or []
            target.synced_at = datetime.utcnow()
            target.ctr = (clicks / impressions) if impressions else 0.0
            target.cpc = (to_major(spend) / clicks) if clicks else 0.0
            target.cpm = (to_major(spend) / impressions * 1000) if impressions else 0.0
            target.extra_data = row
            count += 1

        self.db.commit()
        logger.info(
            f"[AdsManager] 账户 {account.account_id} 洞察落库 {count} 条 "
            f"({start_date} ~ {end_date})"
        )
        return count

    def fetch_delivery_insights(self, account_id: str, start_date: str, end_date: str) -> Dict[str, int]:
        """按 Campaign / AdSet / Ad 级别同步 Meta 洞察。"""
        account = resolve_ad_account(self.db, account_id)
        if not account:
            return {"campaign": 0, "adset": 0, "ad": 0}
        result = {"campaign": 0, "adset": 0, "ad": 0}
        levels = (("campaign", "campaign"), ("adset", "adset"), ("ad", "ad"))
        for dimension, level in levels:
            rows = self._account_insights(account, start_date, end_date, level)
            for row in rows:
                insight_date = self._parse_date(row.get("date_start") or start_date)
                external_id = row.get(f"{dimension}_id")
                if not insight_date or not external_id:
                    continue
                model, parent = (CampaignInsight, "campaign_id") if dimension == "campaign" else (AdSetInsight, "ad_group_id") if dimension == "adset" else (AdInsight, "ad_id")
                entity = None
                if dimension == "campaign": entity = self.db.query(Campaign).filter(Campaign.campaign_id == external_id, Campaign.ad_account_id == account.id).first()
                elif dimension == "adset": entity = self.db.query(AdGroup).filter(AdGroup.ad_group_id == external_id).first()
                else: entity = self.db.query(Ad).filter(Ad.ad_id == external_id).first()
                if not entity: continue
                filter_column = getattr(model, parent)
                existing = self.db.query(model).filter(filter_column == entity.id, model.date == insight_date).first()
                target = existing or model(id=f"ins_{dimension}_{entity.id}_{insight_date}", **{parent: entity.id}, date=insight_date)
                if not existing: self.db.add(target)
                action_metrics = self._parse_action_metrics(row.get("actions"), row.get("action_values")); target.spend = to_minor(float(row.get("spend", 0) or 0)); target.impressions = int(row.get("impressions", 0) or 0); target.clicks = int(row.get("clicks", 0) or 0); target.conversions = action_metrics["conversions"]; target.link_clicks = action_metrics["link_clicks"]; target.landing_page_views = action_metrics["landing_page_views"]; target.leads = action_metrics["leads"]; target.purchases = action_metrics["purchases"]; target.complete_registrations = action_metrics["complete_registrations"]; target.conversion_value = to_minor(action_metrics["conversion_value"]); target.actions = row.get("actions") or []; target.action_values = row.get("action_values") or []; target.synced_at = datetime.utcnow(); target.ctr = (target.clicks / target.impressions) if target.impressions else 0.0; target.cpc = to_major(target.spend) / target.clicks if target.clicks else 0.0; target.cpm = to_major(target.spend) / target.impressions * 1000 if target.impressions else 0.0; result[dimension] += 1
        self.db.commit()
        return result
    @staticmethod
    def _parse_date(value) -> Optional[date]:
        """把 YYYY-MM-DD 字符串转成 date，失败返回 None"""
        if isinstance(value, date):
            return value
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _parse_conversions(actions) -> int:
        """从 Meta 的 actions 数组里取转化数（取 purchase / lead 等常见类型之和）"""
        if not actions:
            return 0
        total = 0
        for item in actions:
            if not isinstance(item, dict):
                continue
            action_type = item.get('action_type') or ''
            if action_type in (
                'purchase', 'omni_purchase', 'lead', 'omni_lead',
                'complete_registration', 'offsite_conversion',
            ):
                try:
                    total += int(float(item.get('value', 0) or 0))
                except (TypeError, ValueError):
                    continue
        return total

    @staticmethod
    def _parse_action_metrics(actions, action_values=None) -> Dict[str, float]:
        """按 Meta action_type 拆分动作；conversion 保持兼容的汇总口径。"""
        result = {"link_clicks": 0, "landing_page_views": 0, "leads": 0,
                  "purchases": 0, "complete_registrations": 0,
                  "conversions": 0, "conversion_value": 0.0}
        conversion_types = {"purchase", "omni_purchase", "lead", "omni_lead",
                            "complete_registration", "offsite_conversion"}
        for item in actions or []:
            if not isinstance(item, dict):
                continue
            action_type = str(item.get("action_type") or "")
            try:
                value = float(item.get("value", 0) or 0)
            except (TypeError, ValueError):
                continue
            count = int(value)
            if action_type in {"link_click", "inline_link_click", "outbound_click"}:
                result["link_clicks"] += count
            if action_type in {"landing_page_view", "landing_page_views"}:
                result["landing_page_views"] += count
            if action_type in {"lead", "omni_lead"}:
                result["leads"] += count
            if action_type in {"purchase", "omni_purchase"}:
                result["purchases"] += count
            if action_type == "complete_registration":
                result["complete_registrations"] += count
            if action_type in conversion_types:
                result["conversions"] += count
        for item in action_values or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("action_type") or "") in {"purchase", "omni_purchase", "offsite_conversion"}:
                try:
                    result["conversion_value"] += float(item.get("value", 0) or 0)
                except (TypeError, ValueError):
                    pass
        return result
