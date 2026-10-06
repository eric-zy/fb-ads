from datetime import datetime

import pytest
from fastapi import HTTPException

from api.meta_tracking_assets import list_tracking_assets
from models import AdAccount, MetaTrackingAsset, User


def test_tracking_asset_list_reads_local_cache_and_reports_missing(db):
    for key in ("cached", "uncached"):
        db.add(AdAccount(id="tracking-" + key, account_id="act_tracking_" + key))
    db.flush()
    db.add(MetaTrackingAsset(id="tracking-cached-pixel", ad_account_id="tracking-cached",
           meta_ad_account_id="act_tracking_cached", meta_asset_id="pixel-1", asset_type="PIXEL",
           name="Cached Pixel", last_synced_at=datetime.utcnow(), raw_json={"last_fired_time": "2026-10-05"}))
    db.flush()
    user = User(id="tracking-admin", role="tenant_admin", tenant_id="test_tenant")
    result = list_tracking_assets(["tracking-cached", "tracking-uncached"], db, user)
    assert result["source"] == "LOCAL_SNAPSHOT"
    assert result["unsynced_account_ids"] == ["tracking-uncached"]
    assert result["items"][0]["id"] == "pixel-1"
    assert result["items"][0]["account_ids"] == ["tracking-cached"]
    assert result["items"][0]["last_fired_time"] == "2026-10-05"
    with pytest.raises(HTTPException) as exc:
        list_tracking_assets(["tracking-cached"], db, User(id="tracking-user", role="user"))
    assert exc.value.status_code == 403
