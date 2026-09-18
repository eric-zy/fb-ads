"""素材使用事件与日汇总回归测试。"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.tenant import bypass_tenant, tenant_scope
from api.media import _asset_query, _assert_asset_edit_access
from services.account_access import accessible_account_ids
from models import (
    AdAccount,
    CreativeAssetUsageAccountDailyStat,
    CreativeAssetUsageDailyStat,
    CreativeAssetUsageEvent,
    CreativeAsset,
    UserAccount,
)
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
