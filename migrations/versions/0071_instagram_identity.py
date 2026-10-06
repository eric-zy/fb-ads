"""Add account-scoped Instagram identity snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0071_instagram_identity"
down_revision = "0070_revenue_daily_totals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meta_instagram_snapshots",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ad_account_id", sa.String(50), sa.ForeignKey("ad_accounts.id"), nullable=False),
        sa.Column("credential_id", sa.String(50), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime()),
        sa.Column("last_sync_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "ad_account_id", name="uq_instagram_tenant_account"),
    )
    op.create_index("ix_instagram_tenant_account", "meta_instagram_snapshots", ["tenant_id", "ad_account_id"])


def downgrade():
    op.drop_index("ix_instagram_tenant_account", table_name="meta_instagram_snapshots")
    op.drop_table("meta_instagram_snapshots")
