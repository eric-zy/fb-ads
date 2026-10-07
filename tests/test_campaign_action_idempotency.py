"""Batch action keys must fit PostgreSQL VARCHAR(128) and remain replayable."""
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from api.campaigns import CampaignActionRequest, campaign_action
from core.idempotency import bounded_idempotency_key
from models import AdAccount, AdSetInstance, CampaignInstance, CampaignJob, CampaignJobItem, CampaignTemplate, DeliveryAction, User
from services.account_operation_lease import AccountOperationLeaseService


REQUEST_KEY = "DELETE:5acef26d2037436abb1e3e372faca353,b7d4081036284c608a4bd01ba68726c4:1791341402793:760e084b7530f"
CAMPAIGN_IDS = ["5acef26d2037436abb1e3e372faca353", "b7d4081036284c608a4bd01ba68726c4"]


@pytest.fixture
def action_context(db, monkeypatch):
    user = User(id="action-admin", username="action-admin", email="action-admin@test.local", hashed_password="unused", role="tenant_admin", tenant_id="test_tenant")
    template = CampaignTemplate(id="12345678901234567890123456789012", name="Action template", tenant_id="test_tenant", creative_config_json={})
    accounts = [AdAccount(id=f"action-account-{i}", account_id=f"act_{i}", account_name=f"Account {i}", tenant_id="test_tenant") for i in range(2)]
    db.add_all([user, template, *accounts])
    db.flush()
    instances = [CampaignInstance(id=campaign_id, template_id=template.id, ad_account_id=account.id, meta_campaign_id=f"remote-{i}", tenant_id="test_tenant") for i, (campaign_id, account) in enumerate(zip(CAMPAIGN_IDS, accounts))]
    db.add_all(instances)
    db.flush()
    leases = {account.id: AccountOperationLeaseService(db).acquire("test_tenant", account.id, user.id, "CAMPAIGN_ACTION").lease_token for account in accounts}
    db.commit()

    # SQLite does not enforce VARCHAR length; enforce the production column
    # contract at flush so this request catches the original PostgreSQL failure.
    def enforce_varchar_lengths(session, flush_context, objects):
        for row in session.new:
            if isinstance(row, (CampaignJob, DeliveryAction)) and row.idempotency_key:
                assert len(row.idempotency_key) <= row.__table__.c.idempotency_key.type.length

    event.listen(db, "before_flush", enforce_varchar_lengths)
    monkeypatch.setattr("services.meta.AdAccountService.filter_available_ids", lambda self, ids, **kwargs: (list(ids), []))
    yield user, instances, leases
    event.remove(db, "before_flush", enforce_varchar_lengths)


def test_batch_campaign_delete_long_key_and_replay(db, monkeypatch, action_context):
    user, instances, leases = action_context
    dispatched = []
    def dispatch(*, args, task_id):
        dispatched.append(args)
        return SimpleNamespace(id=task_id)
    monkeypatch.setattr("api.campaigns.update_delivery_object_task", SimpleNamespace(apply_async=dispatch))
    request = CampaignActionRequest(action="DELETE", object_type="CAMPAIGN", ids=CAMPAIGN_IDS,
                                    operation_leases=leases, idempotency_key=REQUEST_KEY)
    first = campaign_action(request, db, user)
    repeated = campaign_action(request, db, user)
    assert first["action_ids"] == repeated["action_ids"]
    assert len(dispatched) == 2
    assert {args[1] for args in dispatched} == set(CAMPAIGN_IDS)
    assert db.query(CampaignJob).count() == 0
    assert all(len(row.idempotency_key) <= 128 for row in db.query(DeliveryAction))


def test_batch_adset_delete_long_key_and_replay(db, monkeypatch, action_context):
    user, instances, leases = action_context
    adsets = [AdSetInstance(id=f"adset-{i}".ljust(32, "x"), campaign_instance_id=instance.id, meta_adset_id=f"remote-adset-{i}", tenant_id="test_tenant") for i, instance in enumerate(instances)]
    db.add_all(adsets)
    db.commit()
    dispatched = []

    def dispatch(*, args, task_id):
        dispatched.append(args)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("api.campaigns.update_delivery_object_task", SimpleNamespace(apply_async=dispatch))
    request = CampaignActionRequest(action="DELETE", object_type="ADSET", ids=[row.id for row in adsets], operation_leases=leases, idempotency_key=REQUEST_KEY)
    first = campaign_action(request, db, user)
    repeated = campaign_action(request, db, user)
    assert first["action_ids"] == repeated["action_ids"]
    assert len(dispatched) == 2
    rows = db.query(DeliveryAction).all()
    assert len(rows) == 2
    assert len({row.idempotency_key for row in rows}) == 2
    assert all(len(row.idempotency_key) <= 128 for row in rows)


def test_short_legacy_keys_remain_unchanged():
    assert bounded_idempotency_key("legacy-request:template") == "legacy-request:template"
    assert bounded_idempotency_key("x" * 129) != bounded_idempotency_key("x" * 128 + "y")
