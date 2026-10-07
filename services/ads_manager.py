from typing import Optional, Dict, Tuple, Any
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import (
    AccountInsight,
    CampaignInsight,
    AdSetInsight,
    AdInsight,
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
from core.reporting_time import account_today
from services.revenue import update_financial_metrics
from core.redis_client import redis_client
import hashlib
from decimal import Decimal, InvalidOperation


def _minor_int(value) -> Optional[int]:
    """Meta 的 budget 字段返回最小货币单位字符串（"10000" = $100.00）"""
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.to_integral_value():
            raise ValueError("Meta 预算字段必须为整数")
        return int(amount)
    except (TypeError, ValueError, InvalidOperation):
        return None


class AdsManager:
    """广告管理服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.preloaded_reports = None
        self.commit_reports = True

    def _account_insights(self, account: AdAccount, start_date: str, end_date: str, level: str):
        """使用账户绑定凭据访问 Meta，禁止回退到全局单例客户端。"""
        if self.preloaded_reports is not None:
            return self.preloaded_reports[level]
        ref = CredentialResolver(self.db).for_account(account.id)
        response = FBConnectorClient().get_insights(
            account.account_id, ref.credential_id,
            level=level, since=start_date, until=end_date,
        )
        if response.get("complete") is not True or response.get("time_increment") != 1:
            raise ValueError("Connector 未确认完整的逐日报表，请先升级海外 Connector")
        rows = response.get("items")
        self._validate_daily_rows(rows, start_date, end_date, account)
        return rows
    
    @staticmethod
    def _validate_daily_rows(rows, start_date, end_date, account):
        if not isinstance(rows, list):
            raise ValueError("报表 items 必须为数组")
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        seen = set()
        for row in rows:
            day = date.fromisoformat(str(row.get("date_start", "")))
            if row.get("date_stop") != str(day) or not start <= day <= end:
                raise ValueError("报表必须按天返回且位于请求窗口内，拒绝写入区间聚合数据")
            if row.get("account_id") and str(row["account_id"]).removeprefix("act_") != str(account.account_id).removeprefix("act_"):
                raise ValueError("报表账户与请求账户不匹配")
            if row.get("account_currency") and row["account_currency"] != account.currency:
                raise ValueError("Meta 报表币种与本地账户币种不一致，请同步账户信息")
            key = (day, row.get("campaign_id"), row.get("adset_id"), row.get("ad_id"))
            if key in seen:
                raise ValueError("报表返回重复对象日期，拒绝覆盖")
            seen.add(key)

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
            raise
    
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
            account = resolve_ad_account(self.db, account_id)
            yesterday = account_today(account) - timedelta(days=1)
            
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
                            response = FBConnectorClient().pause_campaign(
                                campaign.campaign_id,
                                ref.credential_id,
                                idempotency_key=f"pause:{campaign.campaign_id}:{yesterday}",
                            )
                            from services.meta_updates import confirmed_fields, project_status
                            observed = confirmed_fields(response, {"status": "PAUSED"})
                            project_status(self.db, account.id, "CAMPAIGN", campaign.campaign_id, "PAUSED", observed.get("effective_status"))
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
            today = account_today(account)
            insights = self._account_insights(account, str(today), str(today), 'account')
            
            if insights:
                return to_minor(insights[0].get('spend', 0) or 0, account.currency)
            
            return 0
            
        except Exception as e:
            logger.error(f"Failed to get account spend: {str(e)}")
            # 风控不能把“无法读取花费”当成真实的 0，否则会跳过超预算保护。
            raise

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
            logger.exception(f"[AdsManager] 拉取洞察失败 {account.account_id}: {e}")
            self.db.rollback()
            raise

        if not insights:
            return 0

        # Lock after the remote read, using the same account lock as income
        # imports and callbacks so financial values update as one transaction.
        account = self.db.query(AdAccount).filter(AdAccount.id == account.id).with_for_update().one()
        count = 0
        for row in insights:
            insight_date = date.fromisoformat(row["date_start"])
            if not insight_date:
                continue

            spend = to_minor(row.get('spend', 0) or 0, account.currency)
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
                    id="ins_" + hashlib.sha256(f"{account.id}:{insight_date}".encode()).hexdigest()[:32],
                    ad_account_id=account.id,
                    date=insight_date,
                )
                self.db.add(target)

            target.spend = spend
            update_financial_metrics(target)
            target.impressions = impressions
            target.clicks = clicks
            target.conversions = action_metrics["conversions"]
            target.link_clicks = action_metrics["link_clicks"]
            target.landing_page_views = action_metrics["landing_page_views"]
            target.leads = action_metrics["leads"]
            target.purchases = action_metrics["purchases"]
            target.complete_registrations = action_metrics["complete_registrations"]
            target.conversion_value = to_minor(action_metrics["conversion_value"], account.currency)
            target.actions = row.get("actions") or []
            target.action_values = row.get("action_values") or []
            target.synced_at = datetime.utcnow()
            target.ctr = (clicks / impressions) if impressions else 0.0
            target.cpc = (to_major(spend, account.currency) / clicks) if clicks else 0.0
            target.cpm = (to_major(spend, account.currency) / impressions * 1000) if impressions else 0.0
            target.extra_data = row
            count += 1

        if self.commit_reports:
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
                insight_date = date.fromisoformat(row["date_start"])
                external_id = row.get(f"{dimension}_id")
                if not external_id:
                    raise ValueError(f"{dimension} 报表缺少 Meta ID")
                model, parent = (CampaignInsight, "campaign_id") if dimension == "campaign" else (AdSetInsight, "ad_group_id") if dimension == "adset" else (AdInsight, "ad_id")
                entity = None
                if dimension == "campaign": entity = self.db.query(Campaign).filter(Campaign.campaign_id == external_id, Campaign.ad_account_id == account.id).first()
                elif dimension == "adset": entity = self.db.query(AdGroup).join(Campaign).filter(AdGroup.ad_group_id == external_id, Campaign.ad_account_id == account.id).first()
                else: entity = self.db.query(Ad).join(AdGroup).join(Campaign).filter(Ad.ad_id == external_id, Campaign.ad_account_id == account.id).first()
                if not entity:
                    raise ValueError(f"{dimension} 报表对象 {external_id} 缺少账户内映射，请同步对象后重试")
                filter_column = getattr(model, parent)
                existing = self.db.query(model).filter(filter_column == entity.id, model.date == insight_date).first()
                # Keep insight IDs within the VARCHAR(50) schema limit.  Internal
                # entity IDs are already 32-char hashes, so including the
                # dimension and date verbatim can exceed the column length.
                insight_key = hashlib.sha256(
                    f"{dimension}:{entity.id}:{insight_date}".encode("utf-8")
                ).hexdigest()[:32]
                target = existing or model(id=f"ins_{insight_key}", **{parent: entity.id}, date=insight_date)
                if not existing: self.db.add(target)
                action_metrics = self._parse_action_metrics(row.get("actions"), row.get("action_values")); target.spend = to_minor(row.get("spend", 0) or 0, account.currency); update_financial_metrics(target); target.impressions = int(row.get("impressions", 0) or 0); target.clicks = int(row.get("clicks", 0) or 0); target.conversions = action_metrics["conversions"]; target.link_clicks = action_metrics["link_clicks"]; target.landing_page_views = action_metrics["landing_page_views"]; target.leads = action_metrics["leads"]; target.purchases = action_metrics["purchases"]; target.complete_registrations = action_metrics["complete_registrations"]; target.conversion_value = to_minor(action_metrics["conversion_value"], account.currency); target.actions = row.get("actions") or []; target.action_values = row.get("action_values") or []; target.synced_at = datetime.utcnow(); target.ctr = (target.clicks / target.impressions) if target.impressions else 0.0; target.cpc = to_major(target.spend, account.currency) / target.clicks if target.clicks else 0.0; target.cpm = to_major(target.spend, account.currency) / target.impressions * 1000 if target.impressions else 0.0; result[dimension] += 1
        if self.commit_reports:
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
        return AdsManager._parse_action_metrics(actions)["conversions"]

    @staticmethod
    def _parse_action_metrics(actions, action_values=None) -> Dict[str, Any]:
        def parse(items):
            values = {}
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                try:
                    value = Decimal(str(item.get("value", 0) or 0))
                    if value.is_finite() and value >= 0:
                        values[str(item.get("action_type") or "")] = value
                except (ValueError, TypeError, InvalidOperation):
                    pass
            return values

        def first(values, *aliases):
            return next((values[key] for key in aliases if key in values), Decimal(0))

        counts = parse(actions)
        values = parse(action_values)
        result = {
            "link_clicks": int(first(counts, "link_click", "inline_link_click", "outbound_click")),
            "landing_page_views": int(first(counts, "landing_page_view", "landing_page_views")),
            "leads": int(first(counts, "omni_lead", "lead")),
            "purchases": int(first(counts, "omni_purchase", "purchase")),
            "complete_registrations": int(first(counts, "complete_registration")),
            "conversion_value": first(values, "omni_purchase", "purchase", "offsite_conversion"),
        }
        result["conversions"] = result["leads"] + result["purchases"] + result["complete_registrations"]
        if not any(key in counts for key in ("omni_lead", "lead", "omni_purchase", "purchase", "complete_registration")):
            result["conversions"] = int(first(counts, "offsite_conversion"))
        return result
