from types import SimpleNamespace

from models import AdAccount, AdInstance, AdSetInstance, CampaignInstance, CampaignTemplate, CreativeAsset
from services.media_binding_service import find_missing_asset_ids
from scripts.check_reconciliation_duplicates import _duplicate_rows
from tasks.campaign_tasks import _resolve_adset_for_remote_ad, _store_connector_instances


def test_remote_ad_is_attached_by_parent_adset_id_before_position():
    first = SimpleNamespace(id="local-1")
    second = SimpleNamespace(id="local-2")

    resolved = _resolve_adset_for_remote_ad(
        {"id": "ad-1-2", "adset_id": "meta-adset-2", "client_key": "ad-1-2"},
        adsets_by_id={"meta-adset-2": second},
        adsets_by_key={"adset-1": first, "adset-2": second},
        ordered_adsets=[first, second],
    )

    assert resolved is second


def test_remote_ad_uses_client_key_for_legacy_parent_mapping():
    first = SimpleNamespace(id="local-1")
    second = SimpleNamespace(id="local-2")

    resolved = _resolve_adset_for_remote_ad(
        {"id": "remote-ad", "client_key": "ad-2-3"},
        adsets_by_id={},
        adsets_by_key={"adset-1": first, "adset-2": second},
        ordered_adsets=[first, second],
    )

    assert resolved is second


def test_missing_asset_ids_include_wrong_tenant_assets(db):
    db.add(
        CreativeAsset(
            id="asset-owned",
            tenant_id="test_tenant",
            name="owned.jpg",
            asset_type="image",
        )
    )
    db.add(
        CreativeAsset(
            id="asset-other",
            tenant_id="other-tenant",
            name="other.jpg",
            asset_type="image",
        )
    )
    db.commit()

    assert find_missing_asset_ids(
        db,
        ["asset-owned", "asset-missing"],
        tenant_id="test_tenant",
    ) == ["asset-missing"]
    assert find_missing_asset_ids(
        db,
        ["asset-other"],
        tenant_id="test_tenant",
    ) == ["asset-other"]


def test_reconciliation_duplicate_check_is_empty_for_unique_mappings(db):
    assert _duplicate_rows(
        db,
        AdSetInstance,
        ("campaign_instance_id", "meta_adset_id"),
    ) == []


def test_connector_names_follow_client_keys_even_when_result_order_changes(db):
    account = AdAccount(id="name-account", account_id="act_names")
    template = CampaignTemplate(id="name-template", name="系列名称")
    campaign = CampaignInstance(id="name-campaign", tenant_id="test_tenant", template_id=template.id, ad_account_id=account.id)
    db.add_all([account, template, campaign]); db.flush()
    protocol = {"adsets": [{"client_key": f"adset-{i}", "name": f"US 广告组 {i}", "creatives": [
        {"ads": [{"client_key": f"ad-{i}-1", "name": f"广告 {i} 中文"}]}]} for i in (1, 2)]}
    objects = {"adsets": [{"client_key": f"adset-{i}", "id": f"set-{i}"} for i in (2, 1)],
        "ads": [{"client_key": f"ad-{i}-1", "id": f"ad-{i}", "adset_id": f"set-{i}"} for i in (1, 2)]}
    _store_connector_instances(db, campaign, objects, protocol); db.flush()
    for i in (1, 2):
        adset = db.query(AdSetInstance).filter_by(meta_adset_id=f"set-{i}").one()
        ad = db.query(AdInstance).filter_by(meta_ad_id=f"ad-{i}").one()
        assert adset.name == f"US 广告组 {i}" and ad.name == f"广告 {i} 中文"
        assert ad.adset_instance_id == adset.id
    # Reconciliation must neither duplicate objects nor overwrite an existing real name.
    ad.name = "Meta 重新命名"
    _store_connector_instances(db, campaign, objects, protocol); db.flush()
    assert db.query(AdSetInstance).count() == db.query(AdInstance).count() == 2
    assert ad.name == "Meta 重新命名"


def test_connector_names_prefer_remote_and_never_display_unmapped_keys(db):
    account = AdAccount(id="remote-name-account", account_id="act_remote_names")
    template = CampaignTemplate(id="remote-name-template", name="Template")
    campaign = CampaignInstance(id="remote-name-campaign", tenant_id="test_tenant", template_id=template.id, ad_account_id=account.id)
    db.add_all([account, template, campaign]); db.flush()
    objects = {"adsets": [{"client_key": "adset-1", "id": "remote-set", "name": "远端组名"}],
        "ads": [{"client_key": "ad-1-1", "id": "remote-ad"}]}
    protocol = {"adsets": [{"client_key": "adset-1", "name": "请求组名"}]}
    _store_connector_instances(db, campaign, objects, protocol); db.flush()
    assert db.query(AdSetInstance).one().name == "远端组名"
    assert db.query(AdInstance).one().name == "Ad remote-ad"
