"""Merge the concurrent migration heads.

Revision ID: 0041_merge_heads
Revises: 0040_ad_account_bm_scope, 0040_creative_asset_usage_daily_stats
"""

revision = "0041_merge_heads"
down_revision = ("0040_ad_account_bm_scope", "0040_creative_asset_usage_daily_stats")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
