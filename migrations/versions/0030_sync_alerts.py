"""add sync alerts
Revision ID: 0030_sync_alerts
Revises: 0029_template_temporary
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_sync_alerts"
down_revision = "0029_template_temporary"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("sync_alerts",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("ad_account_id", sa.String(length=50), nullable=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sync_alerts_tenant_open", "sync_alerts", ["tenant_id", "is_resolved"])
    op.create_index("ix_sync_alerts_ad_account_id", "sync_alerts", ["ad_account_id"])

def downgrade():
    op.drop_index("ix_sync_alerts_ad_account_id", table_name="sync_alerts")
    op.drop_index("ix_sync_alerts_tenant_open", table_name="sync_alerts")
    op.drop_table("sync_alerts")
