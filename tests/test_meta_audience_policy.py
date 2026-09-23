from models import AdAccount, MetaAudienceAsset, MetaAudienceExclusionPolicy, SyncAlert
from services.meta_audience_policy import resolve_required_exclusions, sync_policy_rows
from services.meta_audience_service import MetaAudienceSyncService


def _asset(db, account_id="policy-account", audience_id="aud-1"):
    account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
    if not account:
        account = AdAccount(id=account_id, account_id=f"act_{account_id}", connector_credential_id="conn-1")
        db.add(account)
        db.flush()
    row = MetaAudienceAsset(
        id=f"asset-{audience_id}",
        ad_account_id=account.id,
        meta_ad_account_id=account.account_id,
        meta_audience_id=audience_id,
        name=audience_id,
        last_synced_at=__import__("datetime").datetime.utcnow(),
        last_seen_at=__import__("datetime").datetime.utcnow(),
        sync_status="ACTIVE",
    )
    db.add(row)
    db.commit()
    return account, row


def test_policy_snapshot_and_revoke_do_not_fallback_to_legacy_flag(db):
    account, asset = _asset(db)

    rows = sync_policy_rows(db, account.id, [asset.meta_audience_id], created_by="user-1", reason_code="LEGAL")
    db.commit()
    assert rows[0].reason_code == "LEGAL"
    resolved = resolve_required_exclusions(db, account.id)
    assert resolved["snapshot"]["required_excluded_audience_ids"] == [asset.meta_audience_id]
    assert resolved["snapshot"]["fail_closed"] is True
    assert resolved["snapshot"]["hash"]

    sync_policy_rows(db, account.id, [], created_by="user-1", reason_code="LEGAL")
    db.commit()
    db.refresh(asset)
    assert asset.is_required_exclusion is False
    assert db.query(MetaAudienceExclusionPolicy).filter(
        MetaAudienceExclusionPolicy.meta_audience_asset_id == asset.id,
        MetaAudienceExclusionPolicy.status == "REVOKED",
    ).count() == 1
    assert resolve_required_exclusions(db, account.id)["snapshot"]["required_excluded_audience_ids"] == []


def test_full_sync_marks_missing_audience_without_clearing_policy(db, monkeypatch):
    account, asset = _asset(db, account_id="missing-account", audience_id="aud-1")
    sync_policy_rows(db, account.id, [asset.meta_audience_id], created_by="user-1")
    db.commit()

    monkeypatch.setattr("services.meta_audience_service.settings.FB_ACCESS_MODE", "connector")

    class FakeConnector:
        def list_custom_audiences(self, account_id, credential_id):
            return {"data": []}

    monkeypatch.setattr("services.meta_audience_service.FBConnectorClient", FakeConnector)
    MetaAudienceSyncService(db).sync_account(account.id)
    db.refresh(asset)
    assert asset.sync_status == "MISSING"
    assert resolve_required_exclusions(db, account.id)["snapshot"]["required_excluded_audience_ids"] == ["aud-1"]
    alert = db.query(SyncAlert).filter(SyncAlert.alert_type == "META_AUDIENCE_POLICY").one()
    assert alert.is_resolved is False

    class RecoveringConnector:
        def list_custom_audiences(self, account_id, credential_id):
            return {"data": [{"id": "aud-1", "name": "aud-1", "delivery_status": "READY"}]}

    monkeypatch.setattr("services.meta_audience_service.FBConnectorClient", RecoveringConnector)
    MetaAudienceSyncService(db).sync_account(account.id)
    db.refresh(alert)
    assert alert.is_resolved is True
