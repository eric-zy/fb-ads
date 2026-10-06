import importlib
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect


def test_revenue_migration_upgrade_and_downgrade():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for name in ("tenants", "ad_accounts"):
        Table(name, metadata, Column("id", String(50), primary_key=True))
    metadata.create_all(engine)
    migration = importlib.import_module("migrations.versions.0070_revenue_daily_totals")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            inspector = inspect(connection)
            assert "revenue_daily_totals" in inspector.get_table_names()
            assert {"tenant_id", "ad_account_id", "date", "source", "currency", "revenue", "updated_by"}.issubset(
                {column["name"] for column in inspector.get_columns("revenue_daily_totals")})
            assert inspector.get_unique_constraints("revenue_daily_totals")[0]["column_names"] == ["tenant_id", "ad_account_id", "date", "source"]
            migration.downgrade()
            assert "revenue_daily_totals" not in inspect(connection).get_table_names()
    engine.dispose()
