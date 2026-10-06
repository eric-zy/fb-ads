from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from core.tenant import tenant_scope

from api.jobs import CampaignCreateRequest, CampaignDryRunRequest, _template_config_hash, _validate_preview_for_submit, campaign_dry_run, create_campaign_batch
from models import AdAccount, CampaignJob, CampaignTemplate, MetaAssetBinding, PublishPreview, User


def _preview(db, *, ready=True):
    user = User(id="dry-run-admin", role="tenant_admin", tenant_id="test_tenant")
    account = AdAccount(id="dry-run-account", account_id="123", account_name="Dry Run account", tenant_id="test_tenant")
    template = CampaignTemplate(
        id="dry-run-template", tenant_id="test_tenant", created_by=user.id, name="Dry Run template",
        status="ACTIVE", objective="OUTCOME_TRAFFIC", daily_budget=10, budget_type="DAILY",
        optimization_goal="LINK_CLICKS", billing_event="IMPRESSIONS",
        targeting_json={"geo_locations": {"countries": ["US"]}},
        creative_config_json={"page_id": "page-1", "creatives": [{"asset_id": "asset-1", "landing_url": "https://example.com"}]},
    )
    preview = PublishPreview(
        id="dry-run-preview", tenant_id="test_tenant", created_by=user.id, template_id=template.id,
        account_ids=[account.id], snapshot_hash="dry-run-hash", status="READY",
        request_snapshot={"status": "PAUSED", "budget_override": None}, result_snapshot={},
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db.add_all([account, template, preview])
    if ready:
        db.add(MetaAssetBinding(id="dry-run-binding", tenant_id="test_tenant", ad_account_id=account.id,
                               asset_id="asset-1", meta_asset_id="image-hash-1", meta_asset_type="image", status="READY"))
    db.commit()
    return user, preview


@pytest.mark.parametrize("ready", [True, False])
def test_dry_run_reads_local_bindings_without_jobs_uploads_or_network(db, monkeypatch, ready):
    user, preview = _preview(db, ready=ready)

    def unexpected(*args, **kwargs):
        raise AssertionError("Dry Run must not send requests or queue uploads")

    monkeypatch.setattr("requests.sessions.Session.request", unexpected)
    monkeypatch.setattr("services.job_service.queue_pending_asset_bindings", unexpected)
    result = campaign_dry_run(CampaignDryRunRequest(preview_id=preview.id, snapshot_hash=preview.snapshot_hash), db, user)

    assert result["will_write_meta"] is False
    assert result["passed"] is ready
    assert db.query(CampaignJob).count() == 0
    assert db.query(MetaAssetBinding).count() == int(ready)
    assert not db.new and not db.dirty
    if ready:
        plan = result["accounts"][0]
        assert (plan["campaign_count"], plan["adset_count"], plan["ad_count"]) == (1, 1, 1)
        assert plan["payload"]["adsets"][0]["creatives"][0]["object_story_spec"]["link_data"]["image_hash"] == "image-hash-1"
    else:
        assert "素材尚未完成" in result["errors"][0]["message"]


@pytest.mark.parametrize('changed', [
    {"budget_override": 100}, {"status": "ACTIVE"}, {"sinan_promotion_id": "other-promotion"},
    {"access_business_ids": {"dry-run-account": "other-business"}},
])
def test_preview_rejects_configuration_changes_before_submit(db, changed):
    user, preview = _preview(db)
    preview.request_snapshot = {**preview.request_snapshot, "sinan_promotion_id": None, "access_business_ids": {}}
    db.commit()
    request = CampaignCreateRequest(template_id=preview.template_id, ad_account_ids=preview.account_ids,
                                    preview_id=preview.id, snapshot_hash=preview.snapshot_hash, **changed)
    with pytest.raises(HTTPException) as error:
        _validate_preview_for_submit(db, request, user)
    assert error.value.status_code == 409


def test_dry_run_rejects_template_modified_after_preflight(db):
    user, preview = _preview(db)
    template = db.get(CampaignTemplate, preview.template_id)
    preview.request_snapshot = {**preview.request_snapshot, "template_config_hash": _template_config_hash(template)}
    db.commit()
    template.daily_budget = 200
    db.commit()
    with pytest.raises(HTTPException) as error:
        campaign_dry_run(CampaignDryRunRequest(preview_id=preview.id, snapshot_hash=preview.snapshot_hash), db, user)
    assert error.value.status_code == 409
    assert db.query(CampaignJob).count() == 0


def test_preview_is_not_visible_to_another_tenant_admin(db):
    _, preview = _preview(db)
    other = User(id='other-admin', role='tenant_admin', tenant_id='other-tenant')
    request = CampaignCreateRequest(template_id=preview.template_id, ad_account_ids=preview.account_ids,
                                    preview_id=preview.id, snapshot_hash=preview.snapshot_hash)
    with tenant_scope('other-tenant'), pytest.raises(HTTPException) as error:
        _validate_preview_for_submit(db, request, other)
    assert error.value.status_code == 404


def test_direct_submission_reuses_template_from_reviewed_preview(db, monkeypatch):
    user, preview = _preview(db)
    captured = {}
    monkeypatch.setattr('api.jobs._require_submission_leases', lambda *args: None)

    def unexpected(*args, **kwargs):
        raise AssertionError('Submission must not create another template')

    def submit(*args, **kwargs):
        captured.update(kwargs)
        return {"job_id": 'mock-submitted-job', 'status': 'PENDING', 'total_accounts': 1}

    monkeypatch.setattr('api.jobs._ensure_template', unexpected)
    monkeypatch.setattr('api.jobs._submit', submit)
    request = CampaignCreateRequest(source='DIRECT', inline_config={"name": "ignored unreviewed input"},
                                    ad_account_ids=preview.account_ids, preview_id=preview.id, snapshot_hash=preview.snapshot_hash)
    result = create_campaign_batch(request, db, user)
    assert result['job_id'] == 'mock-submitted-job'
    assert captured['template_id'] == preview.template_id
    assert preview.status == 'SUBMITTED'
    assert db.query(CampaignTemplate).count() == 1
