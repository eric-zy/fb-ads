"""Material tag taxonomy, upload, and shared filter behavior."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException

from api.creative_asset_tags import (
    AssetTagsRequest,
    BatchAssetTagsRequest,
    CategoryUpdateRequest,
    set_asset_tags,
    set_batch_asset_tags,
    update_category,
    validate_tag_ids,
)
from api.media import MediaUploadSessionRequest, _apply_asset_view_filters, create_media_upload_session
from core.tenant import tenant_scope
from models import CreativeAsset, CreativeAssetTag, CreativeAssetTagCategory, Tenant, User


def _user(role="manager"):
    return User(id="tag-user", tenant_id="test_tenant", role=role)


def _taxonomy(db):
    regions = CreativeAssetTagCategory(id="regions", tenant_id="test_tenant", name="地区", selection_mode="SINGLE")
    formats = CreativeAssetTagCategory(id="formats", tenant_id="test_tenant", name="形式", selection_mode="MULTIPLE")
    tags = [
        CreativeAssetTag(id="us", tenant_id="test_tenant", category=regions, name="US"),
        CreativeAssetTag(id="uk", tenant_id="test_tenant", category=regions, name="UK"),
        CreativeAssetTag(id="ugc", tenant_id="test_tenant", category=formats, name="UGC"),
        CreativeAssetTag(id="feed", tenant_id="test_tenant", category=formats, name="Feed"),
    ]
    db.add_all([regions, formats, *tags])
    db.commit()
    return {tag.id: tag for tag in tags}


def _asset(db, asset_id, tags):
    asset = CreativeAsset(
        id=asset_id, tenant_id="test_tenant", name=asset_id, asset_type="image",
        created_by="tag-user", status="READY", storage_status="READY", tags=tags,
    )
    db.add(asset)
    db.commit()
    return asset


def test_single_category_enforced_and_batch_modes(db):
    tags = _taxonomy(db)
    first = _asset(db, "tag-asset-1", [tags["us"]])
    second = _asset(db, "tag-asset-2", [tags["uk"]])
    user = _user()

    with pytest.raises(HTTPException) as exc:
        validate_tag_ids(db, ["us", "uk"], "test_tenant")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        set_batch_asset_tags(BatchAssetTagsRequest(
            asset_ids=[first.id, second.id], tag_ids=["uk"], mode="APPEND",
        ), db, user)
    assert [tag.id for tag in first.tags] == ["us"]

    result = set_batch_asset_tags(BatchAssetTagsRequest(
        asset_ids=[first.id, second.id], tag_ids=["ugc"], mode="APPEND",
    ), db, user)
    assert set(result["tag_ids_by_asset"][first.id]) == {"us", "ugc"}
    assert set(result["tag_ids_by_asset"][second.id]) == {"uk", "ugc"}

    set_batch_asset_tags(BatchAssetTagsRequest(
        asset_ids=[first.id, second.id], tag_ids=["ugc"], mode="REMOVE",
    ), db, user)
    assert {tag.id for tag in first.tags} == {"us"}
    assert {tag.id for tag in second.tags} == {"uk"}

    set_asset_tags(first.id, AssetTagsRequest(tag_ids=["feed"]), db, user)
    assert {tag.id for tag in first.tags} == {"feed"}


def test_filters_or_within_category_and_and_across_categories(db):
    tags = _taxonomy(db)
    _asset(db, "match", [tags["us"], tags["ugc"]])
    _asset(db, "wrong-format", [tags["uk"], tags["feed"]])
    _asset(db, "wrong-region", [tags["ugc"]])
    user = _user()
    query = _apply_asset_view_filters(db.query(CreativeAsset), db, user, tag_ids="us,uk,ugc")
    assert [asset.id for asset in query.all()] == ["match"]
    with pytest.raises(HTTPException) as exc:
        _apply_asset_view_filters(db.query(CreativeAsset), db, user, tag_ids="foreign")
    assert exc.value.status_code == 400


def test_inactive_tags_remain_visible_but_cannot_be_newly_applied(db):
    tags = _taxonomy(db)
    asset = _asset(db, "inactive-existing", [tags["us"]])
    tags["us"].status = "INACTIVE"
    db.commit()
    with pytest.raises(HTTPException):
        validate_tag_ids(db, ["us"], "test_tenant")
    assert [item.id for item in _apply_asset_view_filters(
        db.query(CreativeAsset), db, _user(), tag_ids="us",
    ).all()] == [asset.id]
    set_asset_tags(asset.id, AssetTagsRequest(tag_ids=["us", "feed"]), db, _user())
    assert {tag.id for tag in asset.tags} == {"us", "feed"}
    other = _asset(db, "cannot-add-inactive", [])
    with pytest.raises(HTTPException) as inactive_exc:
        set_asset_tags(other.id, AssetTagsRequest(tag_ids=["us"]), db, _user())
    assert inactive_exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        update_category("regions", CategoryUpdateRequest(selection_mode="SINGLE"), db, _user("user"))
    assert exc.value.status_code == 403


def test_cross_tenant_tag_id_is_rejected(db):
    db.add(Tenant(id="other-tag-tenant", name="Other", slug="other-tag-tenant"))
    db.commit()
    with tenant_scope("other-tag-tenant"):
        category = CreativeAssetTagCategory(id="other-category", name="地区", tenant_id="other-tag-tenant")
        db.add_all([category, CreativeAssetTag(id="other-us", name="US", category=category, tenant_id="other-tag-tenant")])
        db.commit()
    with pytest.raises(HTTPException) as exc:
        validate_tag_ids(db, ["other-us"], "test_tenant")
    assert exc.value.status_code == 400


def test_upload_tags_duplicate_and_version_inheritance(db, monkeypatch):
    tags = _taxonomy(db)

    class FakeStorage:
        def presign_put(self, key, mime):
            return {"url": "https://example.invalid/upload", "method": "PUT"}

    monkeypatch.setattr("api.media.AliyunOSSStorage", FakeStorage)
    user = _user()

    def payload(digest, **extra):
        return MediaUploadSessionRequest(
            name="image.png", asset_type="image", mime_type="image/png", size=123,
            sha256=digest * 64, **extra,
        )

    created = create_media_upload_session(payload("a", tag_ids=["us", "ugc"]), db, user)
    original = db.query(CreativeAsset).filter_by(id=created["asset_id"]).one()
    assert {tag.id for tag in original.tags} == {"us", "ugc"}

    # A completed duplicate keeps the existing tag assignment even if a new upload asks for others.
    original.storage_status = "READY"
    original.status = "READY"
    db.commit()
    duplicate = create_media_upload_session(payload("a", tag_ids=["uk"]), db, user)
    assert duplicate["duplicate"] is True
    assert {tag.id for tag in original.tags} == {"us", "ugc"}

    version = create_media_upload_session(payload("b", version_of_asset_id=original.id), db, user)
    inherited = db.query(CreativeAsset).filter_by(id=version["asset_id"]).one()
    assert {tag.id for tag in inherited.tags} == {"us", "ugc"}

    with pytest.raises(HTTPException) as exc:
        create_media_upload_session(payload("c", tag_ids=["missing"]), db, user)
    assert exc.value.status_code == 400


def test_migration_preserves_legacy_tag_links():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE tenants (id VARCHAR(50) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE creative_assets (id VARCHAR(50) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE creative_asset_tags (id VARCHAR(50) PRIMARY KEY, tenant_id VARCHAR(50) NOT NULL, name VARCHAR(64) NOT NULL, color VARCHAR(20), CONSTRAINT uq_creative_asset_tags_tenant_name UNIQUE (tenant_id, name))"))
        conn.execute(sa.text("CREATE TABLE creative_asset_tag_links (asset_id VARCHAR(50), tag_id VARCHAR(50), PRIMARY KEY (asset_id, tag_id))"))
        conn.execute(sa.text("INSERT INTO tenants VALUES ('tenant-a')"))
        conn.execute(sa.text("INSERT INTO creative_assets VALUES ('asset-a')"))
        conn.execute(sa.text("INSERT INTO creative_asset_tags VALUES ('tag-a', 'tenant-a', 'legacy', NULL)"))
        conn.execute(sa.text("INSERT INTO creative_asset_tag_links VALUES ('asset-a', 'tag-a')"))
        path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0072_asset_tag_categories.py"
        spec = importlib.util.spec_from_file_location("asset_tag_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        tag = conn.execute(sa.text("SELECT id, category_id FROM creative_asset_tags WHERE id='tag-a'")).one()
        category = conn.execute(sa.text("SELECT name FROM creative_asset_tag_categories WHERE id=:id"), {"id": tag.category_id}).scalar_one()
        link = conn.execute(sa.text("SELECT asset_id, tag_id FROM creative_asset_tag_links")).one()
        assert (tag.id, category, tuple(link)) == ("tag-a", "未分类", ("asset-a", "tag-a"))
    engine.dispose()
