"""Record complete daily report windows and raw snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0073_report_sync_runs"
down_revision = "0072_asset_tag_categories"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_sync_runs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("account_id", sa.String(50), sa.ForeignKey("ad_accounts.id"), nullable=False),
        sa.Column("task_id", sa.String(100)),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshots", sa.JSON()),
        sa.Column("error", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("ix_report_sync_runs_tenant_id", "report_sync_runs", ["tenant_id"])
    op.create_index("ix_report_sync_runs_account_finished", "report_sync_runs", ["account_id", "finished_at"])


def downgrade():
    op.drop_table("report_sync_runs")
