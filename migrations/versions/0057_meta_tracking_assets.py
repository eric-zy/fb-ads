"""Persist account-scoped Meta Pixel / Dataset metadata."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0057_meta_tracking_assets"
down_revision: Union[str, None] = "0056_oss_multipart_upload_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("meta_tracking_assets"):
        return
    op.create_table(
        "meta_tracking_assets",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("ad_account_id", sa.String(50), nullable=False),
        sa.Column("meta_ad_account_id", sa.String(64), nullable=False),
        sa.Column("meta_asset_id", sa.String(128), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("usable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("ad_account_id", "meta_asset_id", "asset_type", name="uq_meta_tracking_account_asset"),
    )
    op.create_index("ix_meta_tracking_assets_id", "meta_tracking_assets", ["id"])
    op.create_index("ix_meta_tracking_assets_ad_account_id", "meta_tracking_assets", ["ad_account_id"])
    op.create_index("ix_meta_tracking_assets_meta_ad_account_id", "meta_tracking_assets", ["meta_ad_account_id"])
    op.create_index("ix_meta_tracking_tenant_account", "meta_tracking_assets", ["tenant_id", "ad_account_id"])
    op.create_index("ix_meta_tracking_tenant_status", "meta_tracking_assets", ["tenant_id", "status"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("meta_tracking_assets"):
        op.drop_table("meta_tracking_assets")
