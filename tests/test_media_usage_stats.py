"""素材使用事件与日汇总回归测试。"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.tenant import bypass_tenant, tenant_scope
from api.media import (
    _apply_asset_view_filters,
    _asset_query,
    _assert_asset_edit_access,
    get_media_performance_stats,
)
from services.account_access import accessible_account_ids
from models import (
    AdAccount,
    CreativeAssetUsageAccountDailyStat,
    CreativeAssetUsageDailyStat,
    CreativeAssetUsageEvent,
    CreativeAsset,
    Campaign,
    AdGroup,
    Ad,
    AdInsight,
    PublishedAd,
    UserAccount,
)
from models.creative_asset_tag import creative_asset_tag_links
from services.media_usage import record_usage_event
from tasks import media_usage_tasks


@pytest.fixture()
def stats_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    monkeypatch.setattr(media_usage_tasks, "SessionLocal", session_factory)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_record_usage_event_is_idempotent(stats_db):
    with tenant_scope("tenant-a"):
        event = record_usage_event(
            stats_db,
            tenant_id="tenant-a",
            event_key="publish-1:asset-1",
            asset_id="asset-1",
            status="PENDING",
            ad_account_id="account-1",
        )
        stats_db.commit()

        updated = record_usage_event(
            stats_db,
            tenant_id="tenant-a",
            event_key="publish-1:asset-1",
            asset_id="asset-1",
            status="SUCCESS",
            ad_account_id="account-1",
            external_id="ad-1",
        )
        stats_db.commit()

    assert updated.id == event.id
    with tenant_scope("tenant-a"):
        assert stats_db.query(CreativeAssetUsageEvent).filter(
            CreativeAssetUsageEvent.tenant_id == "tenant-a",
            CreativeAssetUsageEvent.event_key == "publish-1:asset-1",
        ).count() == 1
    assert updated.status == "SUCCESS"
    assert updated.external_id == "ad-1"


def test_rebuild_usage_daily_stats_is_tenant_safe_and_repeatable(stats_db):
    today = datetime.utcnow().replace(hour=10, minute=0, second=0, microsecond=0)
    stats_db.add_all([
        CreativeAssetUsageEvent(
            id="event-a-1",
            tenant_id="tenant-a",
            event_key="a-1",
            asset_id="asset-1",
            status="SUCCESS",
            ad_account_id="account-1",
            occurred_at=today,
        ),
        CreativeAssetUsageEvent(
            id="event-a-2",
            tenant_id="tenant-a",
            event_key="a-2",
            asset_id="asset-1",
            status="FAILED",
            ad_account_id="account-1",
            occurred_at=today + timedelta(hours=1),
        ),
        CreativeAssetUsageEvent(
            id="event-a-3",
            tenant_id="tenant-a",
            event_key="a-3",
            asset_id="asset-1",
            status="SUCCESS",
            ad_account_id="account-2",
            occurred_at=today + timedelta(hours=2),
        ),
        CreativeAssetUsageEvent(
            id="event-b-1",
            tenant_id="tenant-b",
            event_key="b-1",
            asset_id="asset-1",
            status="SUCCESS",
            ad_account_id="account-9",
            occurred_at=today,
        ),
    ])
    stats_db.commit()

    result = media_usage_tasks.rebuild_usage_daily_stats.run(days=1)
    assert result["rows"] == 2
    assert result["account_rows"] == 3

    with bypass_tenant():
        daily_rows = stats_db.query(CreativeAssetUsageDailyStat).all()
        account_rows = stats_db.query(CreativeAssetUsageAccountDailyStat).all()
    assert sorted((row.tenant_id, row.usage_count, row.successful_usage_count, row.failed_usage_count)
                  for row in daily_rows) == [
        ("tenant-a", 3, 2, 1),
        ("tenant-b", 1, 1, 0),
    ]
    assert sorted((row.tenant_id, row.ad_account_id, row.usage_count)
                  for row in account_rows) == [
        ("tenant-a", "account-1", 2),
        ("tenant-a", "account-2", 1),
        ("tenant-b", "account-9", 1),
    ]

    # 重复执行先清理时间窗口再重算，结果不应翻倍。
    repeated = media_usage_tasks.rebuild_usage_daily_stats.run(days=1)
    assert repeated["rows"] == 2
    assert repeated["account_rows"] == 3
    with bypass_tenant():
        assert stats_db.query(CreativeAssetUsageDailyStat).count() == 2
        assert stats_db.query(CreativeAssetUsageAccountDailyStat).count() == 3
        assert stats_db.query(CreativeAssetUsageDailyStat).filter(
            CreativeAssetUsageDailyStat.tenant_id == "tenant-a"
        ).one().usage_count == 3


def test_assets_are_shared_between_users_but_isolated_between_tenants(stats_db):
    stats_db.add_all([
        CreativeAsset(
            id="asset-a",
            tenant_id="tenant-a",
            name="A 上传的素材",
            created_by="user-a",
            visibility="ACCOUNT",
            asset_type="image",
            status="READY",
        ),
        CreativeAsset(
            id="asset-b",
            tenant_id="tenant-b",
            name="B 租户素材",
            created_by="user-b",
            visibility="ACCOUNT",
            asset_type="image",
            status="READY",
        ),
    ])
    stats_db.commit()

    with tenant_scope("tenant-a"):
        visible_to_a = {asset.id for asset in _asset_query(stats_db, object()).all()}
    with tenant_scope("tenant-b"):
        visible_to_b = {asset.id for asset in _asset_query(stats_db, object()).all()}

    assert visible_to_a == {"asset-a"}
    assert visible_to_b == {"asset-b"}


def test_shared_asset_write_access_stays_with_uploader_or_admin():
    asset = CreativeAsset(
        id="asset-edit",
        tenant_id="tenant-a",
        name="共享素材",
        created_by="user-a",
        asset_type="image",
    )

    class FakeUser:
        def __init__(self, user_id, admin=False):
            self.id = user_id
            self._admin = admin

        def is_admin(self):
            return self._admin

    _assert_asset_edit_access(asset, FakeUser("user-a"))
    _assert_asset_edit_access(asset, FakeUser("admin", admin=True))
    with pytest.raises(HTTPException) as exc_info:
        _assert_asset_edit_access(asset, FakeUser("user-b"))
    assert exc_info.value.status_code == 403


def test_asset_view_filters_keep_archive_group_tag_and_testing_scope_consistent(stats_db):
    stats_db.add_all([
        CreativeAsset(
            id="asset-view-mine",
            tenant_id="tenant-a",
            name="当前工作区素材",
            created_by="admin",
            group_id="group-a",
            asset_type="image",
            status="READY",
        ),
        CreativeAsset(
            id="asset-view-other",
            tenant_id="tenant-a",
            name="其他素材",
            created_by="other-user",
            group_id="group-b",
            asset_type="image",
            status="READY",
        ),
        CreativeAsset(
            id="asset-view-archive",
            tenant_id="tenant-a",
            name="归档素材",
            created_by="admin",
            group_id="group-a",
            asset_type="image",
            status="ARCHIVED",
        ),
        CreativeAssetUsageDailyStat(
            id="usage-view-mine",
            tenant_id="tenant-a",
            asset_id="asset-view-mine",
            stat_date=datetime.utcnow().date(),
            usage_count=1,
        ),
    ])
    stats_db.execute(creative_asset_tag_links.insert().values(
        asset_id="asset-view-mine",
        tag_id="tag-a",
    ))
    stats_db.commit()

    class FakeAdmin:
        id = "admin"
        tenant_id = "tenant-a"

        def is_admin(self):
            return True

    with tenant_scope("tenant-a"):
        current_scope = _apply_asset_view_filters(
            _asset_query(stats_db, FakeAdmin(), include_archived=False),
            stats_db,
            FakeAdmin(),
            group_id="group-a",
            tag_id="tag-a",
            workspace_mode="testing",
        ).all()
        mine_scope = _apply_asset_view_filters(
            _asset_query(stats_db, FakeAdmin(), include_archived=False),
            stats_db,
            FakeAdmin(),
            workspace_mode="mine",
        ).all()
        archive_scope = _apply_asset_view_filters(
            _asset_query(stats_db, FakeAdmin(), include_archived=True),
            stats_db,
            FakeAdmin(),
            workspace_mode="archive",
        ).all()

    assert {asset.id for asset in current_scope} == {"asset-view-mine"}
    assert {asset.id for asset in mine_scope} == {"asset-view-mine"}
    assert {asset.id for asset in archive_scope} == {"asset-view-archive"}


def test_media_stats_routes_expose_shared_view_filter_contract(client):
    schema = client.get("/openapi.json").json()
    expected = {"group_id", "tag_id", "workspace_mode", "status_filter"}
    for path in ("/api/v1/media", "/api/v1/media/stats/overview", "/api/v1/media/stats/performance"):
        operation = schema["paths"][path]["get"]
        assert expected <= {parameter["name"] for parameter in operation["parameters"]}


def test_media_performance_stats_rejects_invalid_date_range(stats_db):
    class FakeAdmin:
        id = "admin"
        tenant_id = "tenant-a"

        def is_admin(self):
            return True

    with pytest.raises(HTTPException) as exc_info:
        get_media_performance_stats(
            asset_id=None,
            start_date=datetime(2026, 9, 24).date(),
            end_date=datetime(2026, 9, 1).date(),
            asset_type=None,
            account_id=None,
            group_id=None,
            tag_id=None,
            workspace_mode=None,
            status_filter=None,
            include_archived=False,
            db=stats_db,
            user=FakeAdmin(),
        )

    assert exc_info.value.status_code == 400


def test_accessible_accounts_exclude_revoked_expired_and_cross_tenant_assignments(stats_db):
    now = datetime.utcnow()
    stats_db.add_all([
        AdAccount(id="account-active", tenant_id="tenant-a", account_id="act_active"),
        AdAccount(id="account-revoked", tenant_id="tenant-a", account_id="act_revoked"),
        AdAccount(id="account-expired", tenant_id="tenant-a", account_id="act_expired"),
        AdAccount(id="account-other", tenant_id="tenant-b", account_id="act_other"),
        UserAccount(
            id="assignment-active", tenant_id="tenant-a", user_id="user-a",
            account_id="account-active", assignment_status="ACTIVE",
        ),
        UserAccount(
            id="assignment-revoked", tenant_id="tenant-a", user_id="user-a",
            account_id="account-revoked", assignment_status="REVOKED",
        ),
        UserAccount(
            id="assignment-expired", tenant_id="tenant-a", user_id="user-a",
            account_id="account-expired", assignment_status="ACTIVE",
            expires_at=now - timedelta(minutes=1),
        ),
        UserAccount(
            id="assignment-other", tenant_id="tenant-b", user_id="user-a",
            account_id="account-other", assignment_status="ACTIVE",
        ),
    ])
    stats_db.commit()

    class FakeUser:
        id = "user-a"
        tenant_id = "tenant-a"

        def is_admin(self):
            return False

    with tenant_scope("tenant-a"):
        assert accessible_account_ids(stats_db, FakeUser()) == {"account-active"}


def test_media_performance_stats_resolves_published_asset_to_ad_insights(stats_db):
    stats_db.add_all([
        AdAccount(
            id="account-performance",
            tenant_id="tenant-a",
            account_id="act_performance",
            account_name="效果账户",
            currency="USD",
        ),
        CreativeAsset(
            id="asset-performance",
            tenant_id="tenant-a",
            name="效果素材",
            asset_type="image",
            status="READY",
        ),
        Campaign(
            id="campaign-performance",
            tenant_id="tenant-a",
            campaign_id="meta-campaign-performance",
            ad_account_id="account-performance",
            name="效果系列",
        ),
        AdGroup(
            id="adset-performance",
            tenant_id="tenant-a",
            ad_group_id="meta-adset-performance",
            campaign_id="campaign-performance",
            name="效果广告组",
        ),
        Ad(
            id="ad-performance",
            tenant_id="tenant-a",
            ad_id="meta-ad-performance",
            ad_group_id="adset-performance",
            name="效果广告",
        ),
        PublishedAd(
            id="published-performance",
            tenant_id="tenant-a",
            account_id="account-performance",
            asset_id="asset-performance",
            fb_ad_id="meta-ad-performance",
            status="success",
        ),
        AdInsight(
            id="insight-performance",
            tenant_id="tenant-a",
            ad_id="ad-performance",
            date=datetime.utcnow().date(),
            spend=1234,
            impressions=1000,
            clicks=50,
            conversions=2,
            conversion_value=2468,
            synced_at=datetime.utcnow(),
        ),
    ])
    stats_db.commit()

    class FakeAdmin:
        id = "admin"
        tenant_id = "tenant-a"

        def is_admin(self):
            return True

    with tenant_scope("tenant-a"):
        result = get_media_performance_stats(
            asset_id="asset-performance",
            start_date=None,
            end_date=None,
            asset_type=None,
            account_id=None,
            group_id=None,
            tag_id=None,
            workspace_mode=None,
            status_filter=None,
            include_archived=False,
            db=stats_db,
            user=FakeAdmin(),
        )

    assert result["has_data"] is True
    assert result["mapped_asset_count"] == 1
    assert result["unmapped_asset_count"] == 0
    assert result["currency_totals"][0]["currency"] == "USD"
    item = result["items"][0]
    assert item["spend"] == 12.34
    assert item["impressions"] == 1000
    assert item["clicks"] == 50
    assert item["ctr"] == 5.0
    assert item["cpa"] == 6.17
    assert item["roas"] == 2.0
    assert len(result["series"]) == 1
    assert result["series"][0]["date"] == str(datetime.utcnow().date())
    assert result["series"][0]["impressions"] == 1000
