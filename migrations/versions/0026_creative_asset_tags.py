"""Add tenant-scoped creative asset tags."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0026_creative_asset_tags"
down_revision: Union[str, None] = "0025_creative_asset_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "creative_asset_tags" not in tables:
        op.create_table(
            "creative_asset_tags",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("color", sa.String(20), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.UniqueConstraint("tenant_id", "name", name="uq_creative_asset_tags_tenant_name"),
        )
    if "creative_asset_tag_links" not in tables:
        op.create_table(
            "creative_asset_tag_links",
            sa.Column("asset_id", sa.String(50), nullable=False),
            sa.Column("tag_id", sa.String(50), nullable=False),
            sa.ForeignKeyConstraint(["asset_id"], ["creative_assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tag_id"], ["creative_asset_tags.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("asset_id", "tag_id"),
        )


def downgrade() -> None:
    op.drop_table("creative_asset_tag_links")
    op.drop_table("creative_asset_tags")
