"""记录账户报表洞察同步状态。"""

from alembic import op
import sqlalchemy as sa


revision = "0064_account_insights_sync_status"
down_revision = "0063_reconciliation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ad_accounts",
        sa.Column(
            "insights_sync_status",
            sa.String(length=32),
            nullable=False,
            server_default="NEVER",
        ),
    )
    op.add_column(
        "ad_accounts",
        sa.Column("insights_last_synced_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "ad_accounts",
        sa.Column("insights_last_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ad_accounts", "insights_last_sync_error")
    op.drop_column("ad_accounts", "insights_last_synced_at")
    op.drop_column("ad_accounts", "insights_sync_status")
