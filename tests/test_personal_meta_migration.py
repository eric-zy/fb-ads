import importlib
from datetime import datetime
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_personal_authorization_migration_preserves_unknown_owner_and_backfills_known_grants():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table("tenants", metadata, sa.Column("id", sa.String(50), primary_key=True))
    connections = sa.Table("meta_connections", metadata, sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50)), sa.Column("authorized_by_user_id", sa.String(50)))
    credentials = sa.Table("credentials", metadata, sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50)),
        sa.Column("connection_id", sa.String(50)), sa.Column("granted_by_user_id", sa.String(50)),
        sa.Column("status", sa.String(32)), sa.Column("updated_at", sa.DateTime()))
    assets = []
    for name in ("ad_accounts", "meta_pages", "meta_accounts"):
        assets.append(sa.Table(name, metadata, sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50)), sa.Column("connection_id", sa.String(50)), sa.Column("tasks", sa.JSON())))
    for name in ("campaign_job_items", "meta_asset_bindings"):
        sa.Table(name, metadata, sa.Column("id", sa.String(50), primary_key=True))
    metadata.create_all(engine)
    migration = importlib.import_module("migrations.versions.0074_personal_meta_authorization")
    with engine.begin() as connection:
        connection.execute(connections.insert(), [{"id": "known", "tenant_id": "tenant", "authorized_by_user_id": "publisher"},
            {"id": "unknown", "tenant_id": "tenant", "authorized_by_user_id": None}])
        connection.execute(credentials.insert(), {"id": "known-cred", "tenant_id": "tenant", "connection_id": "known", "granted_by_user_id": "publisher", "status": "ACTIVE", "updated_at": datetime.utcnow()})
        for table in assets:
            connection.execute(table.insert(), [{"id": table.name, "tenant_id": "tenant", "connection_id": "known", "tasks": ["ADVERTISE"]},
                {"id": "foreign-" + table.name, "tenant_id": "other", "connection_id": "known", "tasks": []}])
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            grants = sa.Table("meta_connection_assets", sa.MetaData(), autoload_with=connection)
            rows = connection.execute(sa.select(grants)).mappings().all()
            assert len(rows) == 3
            assert {row["asset_type"] for row in rows} == {"AD_ACCOUNT", "PAGE", "BUSINESS"}
            assert all(row["tenant_id"] == "tenant" and row["connection_id"] == "known" for row in rows)
            expanded = sa.Table("meta_connections", sa.MetaData(), autoload_with=connection)
            known = connection.execute(sa.select(expanded).where(expanded.c.id == "known")).mappings().one()
            unknown = connection.execute(sa.select(expanded).where(expanded.c.id == "unknown")).mappings().one()
            assert known["credential_id"] == "known-cred" and known["version"] == 1
            assert unknown["credential_id"] is None and unknown["authorized_by_user_id"] is None
            migration.downgrade()
            assert "meta_connection_assets" not in sa.inspect(connection).get_table_names()
            assert "credential_id" not in {c["name"] for c in sa.inspect(connection).get_columns("meta_connections")}
    engine.dispose()
