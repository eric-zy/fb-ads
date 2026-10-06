"""Add idempotent daily business revenue imports."""
from alembic import op
import sqlalchemy as sa

revision = "0070_revenue_daily_totals"
down_revision = "0069_connector_insights_tenant"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revenue_daily_totals",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("ad_account_id", sa.String(50), sa.ForeignKey("ad_accounts.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("revenue", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.String(50), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "ad_account_id", "date", "source", name="uq_revenue_daily_source"),
    )
    op.create_index("ix_revenue_daily_tenant_account_date", "revenue_daily_totals", ["tenant_id", "ad_account_id", "date"])


def downgrade():
    op.drop_index("ix_revenue_daily_tenant_account_date", table_name="revenue_daily_totals")
    op.drop_table("revenue_daily_totals")
