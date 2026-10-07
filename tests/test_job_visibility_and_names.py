from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from api import jobs as job_api
from api import campaigns as campaign_api
from models import AdAccount, CampaignInstance, CampaignJob, CampaignJobItem, CampaignJobRevision, CampaignTemplate, DeliveryAction, User
from services.job_display import job_display_names, snapshot_job_names


@pytest.fixture
def records(db, monkeypatch):
    owner = User(id="owner", username="owner", email="owner@local.test", hashed_password="x", role="user")
    peer = User(id="peer", username="peer", email="peer@local.test", hashed_password="x", role="user")
    admin = User(id="admin", username="admin", email="admin@local.test", hashed_password="x", role="tenant_admin")
    account = AdAccount(id="shared-account", account_id="act_123", account_name="Shared")
    template = CampaignTemplate(id="names-template", name="His Scent, Her Dreams_第2集", creative_config_json={})
    db.add_all([owner, peer, admin, account, template])
    db.flush()
    campaign = CampaignInstance(id="target", name="Campaign", template_id=template.id, ad_account_id=account.id, meta_campaign_id="meta-target", status="ACTIVE")
    db.add(campaign)
    db.flush()
    for actor in [owner, peer]:
        job = CampaignJob(id=f"{actor.id}-job", template_id=template.id, created_by=actor.id,
                          action_type="CREATE", status="PENDING", scheduled_at=datetime.utcnow() + timedelta(days=1),
                          params={"_display_names": {"campaign_name": "Original", "ad_names": ["Original G1 A1"]}})
        db.add(job)
        db.flush()
        db.add(CampaignJobItem(id=f"{actor.id}-item", job_id=job.id, ad_account_id=account.id, campaign_instance_id=campaign.id, status="PENDING"))
        db.add(CampaignJobRevision(id=f"{actor.id}-revision", base_job_id=job.id, version=1, created_by=actor.id, status="DRAFT"))
        db.add(DeliveryAction(id=f"{actor.id}-action", object_type="CAMPAIGN", object_id="target", account_id=account.id,
                              action="DELETE", requested_by=actor.id, idempotency_key=f"{actor.id}-delete"))
    db.add(CampaignJob(id="unattributed-job", created_by=None))
    db.add(CampaignJob(id="foreign-job", tenant_id="another-tenant", created_by=admin.id))
    db.commit()
    # A shared account must never grant access to another user's task history.
    monkeypatch.setattr(job_api, "accessible_account_ids", lambda *args: {account.id})
    monkeypatch.setattr(campaign_api, "_visible_accounts", lambda *args: {account.id})
    return owner, peer, admin


def listing(db, user, **kwargs):
    response = Response()
    values = dict(status=None, limit=50, page=1, page_size=20, db=db, current_user=user)
    values.update(kwargs)
    return job_api.list_jobs(response=response, **values), response


@pytest.mark.parametrize("role", ["user", "manager", "custom_operator"])
def test_regular_roles_only_see_own_jobs_and_pagination(db, records, role):
    owner, _, _ = records
    owner.role = role
    jobs, response = listing(db, owner)
    assert [job["id"] for job in jobs] == ["owner-job"]
    assert response.headers["X-Total-Count"] == "1"
    jobs, response = listing(db, owner, page=2, page_size=1)
    assert jobs == [] and response.headers["X-Total-Count"] == "1"
    assert [row["id"] for row in job_api.list_scheduled_jobs(50, db, owner)] == ["owner-job"]


def test_admin_sees_all_jobs_in_current_tenant_only(db, records):
    _, _, admin = records
    jobs, response = listing(db, admin)
    assert {row["id"] for row in jobs} == {"owner-job", "peer-job", "unattributed-job"}
    assert response.headers["X-Total-Count"] == "3"
    assert job_api.get_job("peer-job", db, admin)["id"] == "peer-job"
    with pytest.raises(HTTPException) as exc:
        job_api.get_job("foreign-job", db, admin)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("read", [
    lambda db, user: job_api.get_job("peer-job", db, user),
    lambda db, user: job_api.get_edit_source("peer-job", db, user),
    lambda db, user: job_api.get_job_revision("peer-revision", db, user),
    lambda db, user: job_api.list_job_revisions("peer-job", db, user),
    lambda db, user: job_api.cancel_job("peer-job", db, user),
])
def test_guessed_task_ids_cannot_access_shared_account_peer(db, records, read):
    with pytest.raises(HTTPException) as exc:
        read(db, records[0])
    assert exc.value.status_code == 404


def test_own_history_remains_readable_after_account_access_removed(db, records, monkeypatch):
    monkeypatch.setattr(job_api, "accessible_account_ids", lambda *args: set())
    jobs, _ = listing(db, records[0])
    assert jobs[0]["total_accounts"] == 1
    assert job_api.get_job("owner-job", db, records[0])["items"][0]["id"] == "owner-item"
    with pytest.raises(HTTPException):
        job_api.cancel_job("owner-job", db, records[0])


def test_delivery_action_records_are_also_private(db, records):
    owner, _, admin = records
    assert [row["id"] for row in campaign_api.list_delivery_actions(50, None, db, owner)] == ["owner-action"]
    assert len(campaign_api.list_delivery_actions(50, None, db, admin)) == 2
    with pytest.raises(HTTPException) as exc:
        campaign_api.get_delivery_action("peer-action", db, owner)
    assert exc.value.status_code == 404


def test_shared_campaign_details_do_not_leak_peer_task_history(db, records):
    owner, _, admin = records
    detail = campaign_api.campaign_detail("target", db, owner)
    assert detail["job_item"]["id"] == "owner-item"
    assert {row.get("id") or row.get("job_id") for row in detail["recent_actions"]} == {"owner-action", "owner-job"}
    objects = campaign_api.delivery_object_detail("CAMPAIGN", "target", db, owner)
    assert [row["id"] for row in objects["recent_actions"]] == ["owner-action"]
    assert len(campaign_api.campaign_detail("target", db, admin)["recent_actions"]) == 4


def test_names_use_snapshot_then_actual_protocol_not_changed_template(db, records):
    job = db.get(CampaignJob, "owner-job")
    job.template.name = "Renamed template"
    assert job_display_names(job, job.items) == {"campaign_name": "Original", "ad_names": ["Original G1 A1"]}
    job.items[0].response_payload = {"protocol": {
        "campaign": {"name": "Actual campaign"},
        "adsets": [{"creatives": [{"ads": [{"name": "Actual ad 1"}, {"name": "Actual ad 2"}]}]}],
    }}
    payload = job_api.get_job(job.id, db, records[0])
    assert payload["campaign_name"] == "Actual campaign"
    assert payload["ad_names"] == ["Actual ad 1", "Actual ad 2"]
    assert payload["items"][0]["ad_names"] == payload["ad_names"]


@pytest.mark.parametrize("carousel,expected", [(False, ["Series G1 A1", "Series G1 A2"]), (True, ["Series G1 A1"])])
def test_names_match_real_connector_payload(carousel, expected):
    from services.connector_campaign_builder import build_connector_payload
    config = {"page_id": "page", "creatives": [{"image_hash": "h1", "landing_url": "https://example.com"}, {"image_hash": "h2", "landing_url": "https://example.com"}]}
    if carousel:
        config["creative_format"] = "CAROUSEL"
    template = CampaignTemplate(name="Series", objective="OUTCOME_TRAFFIC", daily_budget=10,
                                creative_config_json=config, targeting_json={"geo_locations": {"countries": ["US"]}})
    snapshot = snapshot_job_names(template, "CREATE", {})
    protocol = build_connector_payload(template, "act_123")
    actual = [ad["name"] for group in protocol["adsets"] for creative in group["creatives"] for ad in creative["ads"]]
    assert snapshot["ad_names"] == actual == expected
