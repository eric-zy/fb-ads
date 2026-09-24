from types import SimpleNamespace

from models import AdSetInstance, CreativeAsset
from services.media_binding_service import find_missing_asset_ids
from scripts.check_reconciliation_duplicates import _duplicate_rows
from tasks.campaign_tasks import _resolve_adset_for_remote_ad


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
