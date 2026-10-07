"""Complete snapshots are validated before a single financial transaction."""
import hashlib
import uuid
from datetime import date, datetime

from models import AdAccount, Campaign, AdGroup, Ad, CampaignStatus, ReportSyncRun, AccountInsight, CampaignInsight, AdSetInsight, AdInsight
from services.ads_manager import AdsManager, _minor_int
from services.credential_resolver import CredentialResolver
from services.fb_connector_client import FBConnectorClient
from services.meta_updates import project_status
from services.revenue import update_financial_metrics


def _id(kind, account_id, remote_id):
    return hashlib.sha256(f"{kind}:{account_id}:{remote_id}".encode()).hexdigest()[:32]


def sync_canonical_hierarchy(db, account, remote_campaigns=None, group_cache=None, ad_cache=None):
    """Include objects created outside this platform without inventing templates."""
    connector = FBConnectorClient()
    ref = CredentialResolver(db).for_account(account.id)
    counts = {"campaign": 0, "adset": 0, "ad": 0}
    remote_campaigns = remote_campaigns if remote_campaigns is not None else connector.list_campaigns(account.account_id, ref.credential_id)["campaigns"]
    for remote in remote_campaigns:
        remote_id = str(remote["id"])
        campaign = db.query(Campaign).filter_by(campaign_id=remote_id).first()
        if campaign and campaign.ad_account_id != account.id:
            raise ValueError("广告系列映射到其他账户")
        if not campaign:
            campaign = Campaign(id=_id("campaign", account.id, remote_id), tenant_id=account.tenant_id,
                                campaign_id=remote_id, ad_account_id=account.id, name=remote.get("name") or remote_id)
            db.add(campaign)
        configured = str(remote.get("status") or "PAUSED")
        campaign.name = remote.get("name") or remote_id
        campaign.status = CampaignStatus(configured if configured in {"ACTIVE", "PAUSED", "DELETED"} else "PAUSED")
        campaign.objective = remote.get("objective")
        campaign.daily_budget = _minor_int(remote.get("daily_budget"))
        campaign.budget = _minor_int(remote.get("lifetime_budget"))
        db.flush()
        project_status(db, account.id, "CAMPAIGN", remote_id, campaign.status.value, remote.get("effective_status") or configured)
        counts["campaign"] += 1
        remote_groups = connector.list_adsets(remote_id, ref.credential_id)["adsets"]
        if group_cache is not None:
            group_cache[remote_id] = remote_groups
        for remote_group in remote_groups:
            group_id = str(remote_group["id"])
            group = db.query(AdGroup).filter_by(ad_group_id=group_id).first()
            if group and group.campaign_id != campaign.id:
                raise ValueError("广告组父对象映射不一致")
            if not group:
                group = AdGroup(id=_id("adset", account.id, group_id), tenant_id=account.tenant_id,
                                ad_group_id=group_id, campaign_id=campaign.id, name=remote_group.get("name") or group_id)
                db.add(group)
            group.name = remote_group.get("name") or group_id
            group.status = remote_group.get("status") or "PAUSED"
            group.daily_budget = _minor_int(remote_group.get("daily_budget"))
            db.flush()
            project_status(db, account.id, "ADSET", group_id, group.status, remote_group.get("effective_status"))
            counts["adset"] += 1
            remote_ads = connector.list_ads(group_id, ref.credential_id)["ads"]
            if ad_cache is not None:
                ad_cache[group_id] = remote_ads
            for remote_ad in remote_ads:
                ad_id = str(remote_ad["id"])
                ad = db.query(Ad).filter_by(ad_id=ad_id).first()
                if ad and ad.ad_group_id != group.id:
                    raise ValueError("广告父对象映射不一致")
                if not ad:
                    ad = Ad(id=_id("ad", account.id, ad_id), tenant_id=account.tenant_id,
                            ad_id=ad_id, ad_group_id=group.id, name=remote_ad.get("name") or ad_id)
                    db.add(ad)
                ad.name = remote_ad.get("name") or ad_id
                ad.status = remote_ad.get("status") or "PAUSED"
                ad.creative_id = (remote_ad.get("creative") or {}).get("id")
                db.flush()
                project_status(db, account.id, "AD", ad_id, ad.status, remote_ad.get("effective_status"))
                counts["ad"] += 1
    return counts


def _reset_window(db, account, start, end):
    """A complete snapshot replaces old metrics while retaining imported income."""
    campaigns = db.query(Campaign.id).filter(Campaign.ad_account_id == account.id)
    groups = db.query(AdGroup.id).filter(AdGroup.campaign_id.in_(campaigns))
    ads = db.query(Ad.id).filter(Ad.ad_group_id.in_(groups))
    scopes = [(AccountInsight, AccountInsight.ad_account_id == account.id),
              (CampaignInsight, CampaignInsight.campaign_id.in_(campaigns)),
              (AdSetInsight, AdSetInsight.ad_group_id.in_(groups)),
              (AdInsight, AdInsight.ad_id.in_(ads))]
    for model, scope in scopes:
        for row in db.query(model).filter(scope, model.date >= start, model.date <= end).all():
            for field in ("spend", "impressions", "clicks", "conversions", "link_clicks", "landing_page_views", "leads", "purchases", "complete_registrations", "conversion_value", "ctr", "cpc", "cpm"):
                setattr(row, field, 0)
            row.actions = []
            row.action_values = []
            row.synced_at = datetime.utcnow()
            update_financial_metrics(row)


def sync_report_window(db, account, start, end, task_id=None):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if start > end or (end - start).days >= 90:
        raise ValueError("报表窗口必须为 1 至 90 天")
    run = ReportSyncRun(id=uuid.uuid4().hex, tenant_id=account.tenant_id, account_id=account.id,
                        task_id=task_id, start_date=start, end_date=end, status="RUNNING")
    db.add(run)
    db.commit()
    manager = AdsManager(db)
    snapshots = {}
    try:
        # Preserve raw responses before any hierarchy/financial mutation.
        for level in ("account", "campaign", "adset", "ad"):
            snapshots[level] = manager._account_insights(account, str(start), str(end), level)
        run.snapshots = snapshots
        db.commit()
        account = db.query(AdAccount).filter_by(id=account.id).with_for_update().one()
        hierarchy = sync_canonical_hierarchy(db, account)
        _reset_window(db, account, start, end)
        manager.preloaded_reports = snapshots
        manager.commit_reports = False
        account_count = manager.fetch_insights(account.id, str(start), str(end))
        delivery_counts = manager.fetch_delivery_insights(account.id, str(start), str(end))
        run.status = "SUCCESS"
        run.finished_at = datetime.utcnow()
        account.insights_sync_status = "SUCCESS"
        account.insights_last_synced_at = run.finished_at
        account.insights_last_sync_error = None
        db.commit()
        return {"status": "success", "account_id": account.id, "insights_count": account_count,
                "delivery_counts": delivery_counts, "hierarchy_counts": hierarchy,
                "start_date": str(start), "end_date": str(end), "run_id": run.id}
    except Exception as exc:
        db.rollback()
        run.status = "FAILED"
        run.snapshots = snapshots
        run.error = str(exc)[:2000]
        run.finished_at = datetime.utcnow()
        db.commit()
        raise
