from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from models import AdAccount, Campaign, AdGroup, CampaignJob, CampaignJobItem, CampaignInstance, CampaignTemplate, User
from services.budget_updates import apply_budget_updates


@pytest.fixture
def context(db):
    account = AdAccount(id="budget-account", account_id="act_budget", currency="USD")
    template = CampaignTemplate(id="budget-template", name="Budget template")
    job = CampaignJob(id="budget-job", action_type="UPDATE_BUDGET", template_id=template.id)
    item = CampaignJobItem(id="budget-item", job_id=job.id, ad_account_id=account.id)
    instance = CampaignInstance(id="budget-instance", template_id=template.id, ad_account_id=account.id, meta_campaign_id="remote-c", status="ACTIVE")
    canonical = Campaign(id="budget-canonical", campaign_id="remote-c", ad_account_id=account.id, name="Budget campaign", daily_budget=1000)
    db.add_all([account, template, job, item, instance, canonical]); db.commit()
    connector = SimpleNamespace(list_campaigns=Mock(return_value={"campaigns": [{"id": "remote-c", "status": "ACTIVE"}]}),
                                list_adsets=Mock(return_value={"adsets": []}), update_object=Mock())
    return account, item, instance, canonical, connector


def test_budget_with_no_groups_fails_before_any_meta_write(db, context):
    account, item, instance, _, connector = context
    with pytest.raises(ValueError, match="没有可调整预算"):
        apply_budget_updates(db, item, [instance], account, connector, "credential", "20.50")
    connector.update_object.assert_not_called()


def test_campaign_budget_updates_campaign_and_backfills_local_budget(db, context):
    account, item, instance, canonical, connector = context
    connector.list_campaigns.return_value["campaigns"][0]["daily_budget"] = "1000"
    connector.update_object.return_value = {"result": {"confirmed": True, "daily_budget": "2050"}}
    apply_budget_updates(db, item, [instance], account, connector, "credential", "20.50")
    assert connector.update_object.call_args.args[:2] == ("CAMPAIGN", "remote-c")
    assert canonical.daily_budget == 2050
    connector.list_adsets.assert_not_called()


@pytest.mark.parametrize("budget,currency", [(0, "USD"), (-1, "USD"), ("NaN", "USD"), ("Infinity", "USD"), ("10.001", "USD"), (1000, "JPY")])
def test_budget_rejects_invalid_amount_or_unverified_currency(db, context, budget, currency):
    account, item, instance, _, connector = context
    account.currency = currency
    with pytest.raises(ValueError):
        apply_budget_updates(db, item, [instance], account, connector, "credential", budget)
    connector.update_object.assert_not_called()


def test_lifetime_budget_rejected_without_changing_budget_type(db, context):
    account, item, instance, _, connector = context
    connector.list_adsets.return_value = {"adsets": [{"id": "g1", "status": "ACTIVE", "lifetime_budget": "20000"}]}
    with pytest.raises(ValueError, match="总预算"):
        apply_budget_updates(db, item, [instance], account, connector, "credential", "20")
    connector.update_object.assert_not_called()


def test_budget_partial_failure_keeps_acknowledged_changes_and_retry_skips_them(db, context):
    account, item, instance, canonical, connector = context
    groups = [AdGroup(id=f"budget-group-{i}", ad_group_id=f"g{i}", campaign_id=canonical.id, name="Group", daily_budget=1000) for i in (1, 2)]
    db.add_all(groups); db.commit()
    connector.list_adsets.return_value = {"adsets": [{"id": f"g{i}", "status": "ACTIVE", "daily_budget": "1000"} for i in (1, 2)]}
    connector.update_object.side_effect = [{"result": {"confirmed": True, "daily_budget": "2000"}}, RuntimeError("Meta denied")]
    with pytest.raises(RuntimeError, match="Meta denied"):
        apply_budget_updates(db, item, [instance], account, connector, "credential", "20")
    assert groups[0].daily_budget == 2000
    assert groups[1].daily_budget == 1000
    assert item.response_payload["budget_results"]["ADSET:g2"]["status"] == "FAILED"
    connector.update_object.reset_mock()
    connector.update_object.side_effect = None
    connector.update_object.return_value = {"result": {"confirmed": True, "daily_budget": "2000"}}
    apply_budget_updates(db, item, [instance], account, connector, "credential", "20")
    assert connector.update_object.call_count == 1
    assert connector.update_object.call_args.args[1] == "g2"
    assert groups[1].daily_budget == 2000


def test_api_budget_keeps_selected_instances_across_accounts(db, monkeypatch, context):
    from api.campaigns import CampaignActionRequest, campaign_action
    from services.account_operation_lease import AccountOperationLeaseService
    account, _, instance, _, _ = context
    admin = User(id="budget-admin", username="budget-admin", email="budget@test.local", hashed_password="unused", role="tenant_admin", is_active=True)
    other = AdAccount(id="budget-account-2", account_id="act_budget_2", currency="USD")
    second = CampaignInstance(id="budget-selected-2", template_id=instance.template_id, ad_account_id=other.id, meta_campaign_id="remote-c2", status="ACTIVE")
    db.add_all([admin, other, second]); db.commit()
    lease = AccountOperationLeaseService(db).acquire("test_tenant", account.id, admin.id, "CAMPAIGN_ACTION")
    lease2 = AccountOperationLeaseService(db).acquire("test_tenant", other.id, admin.id, "CAMPAIGN_ACTION")
    db.commit()
    created = []
    def create(self, **kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="new-budget-job", status="PENDING")
    monkeypatch.setattr("api.campaigns.JobService.create_job", create)
    campaign_action(CampaignActionRequest(action="UPDATE_BUDGET", object_type="CAMPAIGN", ids=[instance.id, second.id], budget=20,
                     operation_leases={account.id: lease.lease_token, other.id: lease2.lease_token}), db, admin)
    assert set(created[0]["ad_account_ids"]) == {account.id, other.id}
    assert set(created[0]["params"]["selected_instance_ids"]) == {instance.id, second.id}


@pytest.mark.parametrize("action,permissions,allowed", [
    ("CREATE", ["job:create"], True),
    ("PAUSE", ["job:create"], True),
    ("UPDATE_BUDGET", ["campaign:update_budget"], True),
    ("UPDATE_BUDGET", ["job:create"], False),
    ("DELETE", ["job:create"], False),
])
def test_worker_checks_actual_action_permission(action, permissions, allowed, monkeypatch):
    from tasks import campaign_tasks
    actor = SimpleNamespace(is_admin=lambda: False, permissions=permissions)
    monkeypatch.setattr(campaign_tasks, "task_actor", lambda *args: actor)
    monkeypatch.setattr(campaign_tasks, "require_accounts", lambda *args, **kwargs: None)
    item = SimpleNamespace(tenant_id="test", job=SimpleNamespace(tenant_id="test", created_by="actor", action_type=action, status="PENDING"),
                           ad_account=SimpleNamespace(tenant_id="test", id="account"))
    if allowed:
        assert campaign_tasks._validate_item_actor(None, item) is False
    else:
        with pytest.raises(PermissionError, match="权限已撤销"):
            campaign_tasks._validate_item_actor(None, item)
