"""Personal OAuth ownership and independent asset authorization grants."""
from alembic import op
import sqlalchemy as sa

revision = "0074_personal_meta_authorization"
down_revision = "0073_report_sync_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meta_connections", sa.Column("access_mode", sa.String(20), nullable=False, server_default="direct"))
    op.add_column("meta_connections", sa.Column("credential_id", sa.String(50)))
    op.add_column("meta_connections", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("meta_connections", sa.Column("data_access_expires_at", sa.DateTime()))
    op.create_table("meta_connection_assets",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connection_id", sa.String(50), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("asset_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tasks", sa.JSON()), sa.Column("last_synced_at", sa.DateTime()),
        sa.UniqueConstraint("tenant_id", "connection_id", "asset_type", "asset_id", name="uq_connection_asset"))
    op.create_index("ix_meta_connection_assets_connection_id", "meta_connection_assets", ["connection_id"])
    op.create_index("ix_meta_connection_assets_asset_id", "meta_connection_assets", ["asset_id"])
    op.create_table("meta_oauth_sessions", sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(50), nullable=False), sa.Column("connection_id", sa.String(50)),
        sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("consumed_at", sa.DateTime()))
    op.add_column("campaign_job_items", sa.Column("authorization_connection_id", sa.String(50)))
    op.add_column("campaign_job_items", sa.Column("authorization_version", sa.Integer()))
    op.add_column("meta_asset_bindings", sa.Column("authorization_connection_id", sa.String(50)))
    op.add_column("meta_asset_bindings", sa.Column("requested_by", sa.String(50)))
    # Backfill only known owners. Never guess the owner of legacy Connector IDs.
    bind = op.get_bind()
    metadata = sa.MetaData()
    connections = sa.Table("meta_connections", metadata, autoload_with=bind)
    credentials = sa.Table("credentials", metadata, autoload_with=bind)
    grants = sa.Table("meta_connection_assets", metadata, autoload_with=bind)
    import uuid
    from datetime import datetime
    for row in bind.execute(sa.select(connections)).mappings().all():
        cred = bind.execute(sa.select(credentials).where(credentials.c.connection_id == row["id"],
            credentials.c.tenant_id == row["tenant_id"],
            credentials.c.granted_by_user_id == row["authorized_by_user_id"],
            credentials.c.status == "ACTIVE").order_by(credentials.c.updated_at.desc())).mappings().first()
        if not row["authorized_by_user_id"] or not cred:
            continue
        bind.execute(connections.update().where(connections.c.id == row["id"]).values(credential_id=cred["id"]))
        for table, kind in (("ad_accounts", "AD_ACCOUNT"), ("meta_pages", "PAGE"), ("meta_accounts", "BUSINESS")):
            assets = sa.Table(table, metadata, autoload_with=bind)
            for asset in bind.execute(sa.select(assets).where(assets.c.connection_id == row["id"], assets.c.tenant_id == row["tenant_id"])).mappings():
                bind.execute(grants.insert().values(id=uuid.uuid4().hex, tenant_id=row["tenant_id"],
                    connection_id=row["id"], asset_type=kind, asset_id=asset["id"], status="ACTIVE",
                    tasks=asset.get("tasks") or [], last_synced_at=datetime.utcnow()))


def downgrade():
    op.drop_column("meta_asset_bindings", "requested_by")
    op.drop_column("meta_asset_bindings", "authorization_connection_id")
    op.drop_column("campaign_job_items", "authorization_version")
    op.drop_column("campaign_job_items", "authorization_connection_id")
    op.drop_table("meta_oauth_sessions")
    op.drop_table("meta_connection_assets")
    for column in ("data_access_expires_at", "version", "credential_id", "access_mode"):
        op.drop_column("meta_connections", column)
