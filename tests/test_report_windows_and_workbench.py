from datetime import date, datetime, timedelta

import pytest
from fastapi import HTTPException

from api.reports import account_overview, report_breakdown, report_trend
from api.workbench import workbench_summary, workbench_notifications
from models import AdAccount, Campaign, CampaignInstance, CampaignTemplate, AdGroup, Ad, AccountInsight, CampaignInsight, AdSetInsight, AdInsight, ReportSyncRun, CampaignJob, CampaignJobItem, User, UserAccount


@pytest.fixture
def window(db):
    admin = User(id="window-admin", username="window-admin", email="window@local.test", hashed_password="x", role="tenant_admin")
    account = AdAccount(id="window-account", account_id="act_window", account_name="Window", currency="USD")
    campaign = Campaign(id="window-campaign", campaign_id="remote-window-c", ad_account_id=account.id, name="Campaign", status="ACTIVE")
    group = AdGroup(id="window-group", ad_group_id="remote-window-g", campaign_id=campaign.id, name="Group")
    ad = Ad(id="window-ad", ad_id="remote-window-a", ad_group_id=group.id, name="Ad")
    db.add_all([admin, account, campaign, group, ad]); db.flush()
    start, end = date(2026, 9, 10), date(2026, 9, 12)
    for index, day in enumerate([start - timedelta(days=1), start, end, end + timedelta(days=1)]):
        amount = 100000 if index in [0, 3] else 1000
        for model, key, target in [(AccountInsight, "ad_account_id", account.id), (CampaignInsight, "campaign_id", campaign.id), (AdSetInsight, "ad_group_id", group.id), (AdInsight, "ad_id", ad.id)]:
            db.add(model(id=f"window-{model.__tablename__}-{index}", date=day, spend=amount, impressions=100, clicks=10, conversions=2, **{key: target}))
    db.add(ReportSyncRun(id="window-run", account_id=account.id, start_date=start, end_date=end, status="SUCCESS",
                         snapshots={level: [] for level in ["account", "campaign", "adset", "ad"]}, finished_at=datetime.utcnow()))
    db.commit()
    return admin, account, campaign, group, ad, start, end


@pytest.mark.parametrize("dimension,index", [("account", 1), ("campaign", 1), ("adset", 2), ("ad", 3)])
def test_custom_window_uses_same_dates_for_metrics_and_coverage(db, window, dimension, index):
    admin, account, campaign, group, ad, start, end = window
    result = report_breakdown(dimension=dimension, days=30, parent_id=window[index].id, db=db, current_user=admin, start_date=start, end_date=end)
    assert result["days"] == 3
    assert result["items"][0]["spend"] == 20
    assert result["data_quality"][0]["covered_days"] == result["data_quality"][0]["expected_days"] == 3
    assert result["data_quality"][0]["status"] == "FRESH"
    summary = workbench_summary(start_date=start, end_date=end, db=db, current_user=admin)
    assert summary["currency_totals"][0]["spend"] == result["items"][0]["spend"]
    assert summary["freshness"]["status"] == "FRESH"
    assert summary["kpis"]["total_campaigns"] == summary["kpis"]["active_campaigns"] == 1


def test_custom_trend_and_currency_cpa_use_aggregated_denominators(db, window):
    admin, account, *_, start, end = window
    result = report_trend(dimension="account", days=30, entity_id=account.id, db=db, current_user=admin, start_date=start, end_date=end)
    assert result["total"]["spend"] == 20
    assert [row["date"] for row in result["series"]] == [str(start), str(end)]
    overview = account_overview(start_date=start, end_date=end, db=db, current_user=admin)
    assert overview["currency_totals"][0]["cpa"] == 5
    for row in db.query(AccountInsight).all():
        row.conversions = 0
    db.commit()
    overview = account_overview(start_date=start, end_date=end, db=db, current_user=admin)
    assert overview["currency_totals"][0]["cpa"] is None


@pytest.mark.parametrize("start,end", [(date(2026, 1, 1), None), (None, date(2026, 1, 1)), (date(2026, 1, 2), date(2026, 1, 1)), (date(2026, 1, 1), date(2026, 4, 1))])
def test_custom_window_rejects_partial_reversed_or_more_than_90_days(db, window, start, end):
    with pytest.raises(HTTPException) as exc:
        report_breakdown(dimension="account", days=30, parent_id=None, db=db, current_user=window[0], start_date=start, end_date=end)
    assert exc.value.status_code == 400


def test_workbench_campaigns_include_external_objects_without_duplicate_instances(db, window):
    admin, account, campaign, *_ = window
    template = CampaignTemplate(id="window-template", name="Local template")
    archived_template = CampaignTemplate(id="window-archived-template", name="Archived template")
    db.add_all([template, archived_template]); db.flush()
    db.add(CampaignInstance(id="window-instance", template_id=template.id, ad_account_id=account.id,
                            meta_campaign_id=campaign.campaign_id, name="Local", status="ACTIVE"))
    db.add(CampaignInstance(id="archive-instance", template_id=archived_template.id, ad_account_id=account.id,
                            meta_campaign_id="archived-remote", name="Archived", status="ARCHIVED", desired_status="ARCHIVED", meta_status="PAUSED"))
    db.add(Campaign(id="archived-canonical", campaign_id="archived-remote", ad_account_id=account.id, name="Archived", status="PAUSED"))
    db.commit()
    result = workbench_summary(db=db, current_user=admin)
    assert result["kpis"]["total_campaigns"] == 2
    assert result["kpis"]["active_campaigns"] == 1
    assert result["kpis"]["status_drift"] == 0
    assert result["delivery_health"]["status_counts"]["ARCHIVED"] == 1


def test_workbench_task_counts_and_notifications_follow_owner(db, window):
    admin, account, *_ = window
    owner = User(id="window-owner", username="window-owner", email="owner-window@local.test", hashed_password="x", role="user")
    db.add(owner)
    db.add(UserAccount(id="window-assignment", user_id=owner.id, account_id=account.id, assignment_status="ACTIVE"))
    for actor in [owner, admin]:
        job = CampaignJob(id=f"window-job-{actor.id}", created_by=actor.id, action_type="CREATE", status="FAILED")
        db.add(job); db.flush()
        db.add(CampaignJobItem(id=f"window-item-{actor.id}", job_id=job.id, ad_account_id=account.id, status="FAILED"))
    db.commit()
    result = workbench_summary(db=db, current_user=owner)
    assert result["kpis"]["failed_jobs"] == 1
    assert [row["created_by"] for row in result["recent_tasks"]] == [owner.id]
    assert workbench_notifications(db=db, current_user=owner)["failed_jobs"] == 1
    assert workbench_notifications(db=db, current_user=admin)["failed_jobs"] == 2


@pytest.mark.parametrize("dimension", ["campaign", "adset", "ad"])
def test_empty_complete_child_snapshots_still_have_account_coverage(db, window, dimension):
    admin, _, *_, start, end = window
    empty = AdAccount(id="empty-window-account", account_id="act_empty_window")
    db.add(empty); db.flush()
    db.add(ReportSyncRun(id="empty-window-run", account_id=empty.id, start_date=start, end_date=end, status="SUCCESS",
                         snapshots={level: [] for level in ["account", "campaign", "adset", "ad"]}, finished_at=datetime.utcnow()))
    db.commit()
    result = report_breakdown(dimension=dimension, days=3, parent_id=None, db=db, current_user=admin, start_date=start, end_date=end)
    quality = next(row for row in result["data_quality"] if row["account_id"] == empty.id)
    assert quality["complete"] is True
    assert quality["covered_days"] == quality["expected_days"] == 3
    if dimension == "campaign":
        selected = report_breakdown(dimension=dimension, days=3, parent_id=empty.id, db=db, current_user=admin, start_date=start, end_date=end)
        assert selected["items"] == []
        assert selected["data_quality"] == [{"account_id": empty.id, **{key: value for key, value in quality.items() if key != "account_id"}}]
    owner = User(id="empty-window-owner", username="empty-window-owner", email="empty-window-owner@local.test", hashed_password="x", role="user")
    db.add(owner); db.commit()
    private = report_breakdown(dimension=dimension, days=3, parent_id=None, db=db, current_user=owner, start_date=start, end_date=end)
    assert private["data_quality"] == []
