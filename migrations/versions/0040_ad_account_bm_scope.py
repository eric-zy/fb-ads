"""Make ad account uniqueness scoped to tenant + BM.

Revision ID: 0040_ad_account_bm_scope
Revises: 0039_creative_asset_usage_events
"""
from alembic import op

revision = "0040_ad_account_bm_scope"
down_revision = "0039_creative_asset_usage_events"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_tenant_ad_account", "ad_accounts", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_business_ad_account",
        "ad_accounts",
        ["tenant_id", "business_id", "account_id"],
    )


def downgrade():
    op.drop_constraint("uq_tenant_business_ad_account", "ad_accounts", type_="unique")
    op.create_unique_constraint("uq_tenant_ad_account", "ad_accounts", ["tenant_id", "account_id"])
