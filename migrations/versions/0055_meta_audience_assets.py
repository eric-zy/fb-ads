"""Cache account-scoped Meta Custom Audience assets."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0055_meta_audience_assets"
down_revision: Union[str, None] = "0054_video_thumbnail_bindings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("meta_audience_assets"):
        return
    op.create_table(
        "meta_audience_assets",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("ad_account_id", sa.String(50), nullable=False),
        sa.Column("meta_ad_account_id", sa.String(64), nullable=False),
        sa.Column("meta_audience_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subtype", sa.String(64), nullable=True),
        sa.Column("delivery_status", sa.String(64), nullable=True),
        sa.Column("sharing_status", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="META"),
        sa.Column("is_required_exclusion", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("ad_account_id", "meta_audience_id", name="uq_meta_audience_account"),
    )
    op.create_index("ix_meta_audience_assets_id", "meta_audience_assets", ["id"])
    op.create_index("ix_meta_audience_assets_ad_account_id", "meta_audience_assets", ["ad_account_id"])
    op.create_index("ix_meta_audience_assets_meta_ad_account_id", "meta_audience_assets", ["meta_ad_account_id"])
    op.create_index("ix_meta_audience_tenant_account", "meta_audience_assets", ["tenant_id", "ad_account_id"])
    op.create_index("ix_meta_audience_tenant_required", "meta_audience_assets", ["tenant_id", "is_required_exclusion"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("meta_audience_assets"):
        op.drop_table("meta_audience_assets")
