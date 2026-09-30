"""Add account and requester ownership to Meta sync logs."""

from alembic import op
import sqlalchemy as sa


revision = "0065_meta_sync_log_scope"
down_revision = "0064_account_insights_sync_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meta_sync_logs",
        sa.Column("ad_account_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "meta_sync_logs",
        sa.Column("requested_by", sa.String(length=50), nullable=True),
    )
    op.create_foreign_key(
        "fk_meta_sync_logs_ad_account_id",
        "meta_sync_logs",
        "ad_accounts",
        ["ad_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_meta_sync_logs_requested_by",
        "meta_sync_logs",
        "users",
        ["requested_by"],
        ["id"],
    )
    op.create_index(
        "ix_meta_sync_logs_tenant_account",
        "meta_sync_logs",
        ["tenant_id", "ad_account_id"],
    )
    op.create_index(
        "ix_meta_sync_logs_tenant_requester",
        "meta_sync_logs",
        ["tenant_id", "requested_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_meta_sync_logs_tenant_requester", table_name="meta_sync_logs")
    op.drop_index("ix_meta_sync_logs_tenant_account", table_name="meta_sync_logs")
    op.drop_constraint("fk_meta_sync_logs_requested_by", "meta_sync_logs", type_="foreignkey")
    op.drop_constraint("fk_meta_sync_logs_ad_account_id", "meta_sync_logs", type_="foreignkey")
    op.drop_column("meta_sync_logs", "requested_by")
    op.drop_column("meta_sync_logs", "ad_account_id")
