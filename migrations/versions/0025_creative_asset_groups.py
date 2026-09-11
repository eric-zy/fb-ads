"""Add tenant scoped creative asset groups and members."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0025_creative_asset_groups"
down_revision: Union[str, None] = "0024_creative_asset_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    asset_columns = {column["name"] for column in inspector.get_columns("creative_assets")}
    if "creative_asset_groups" not in tables:
        op.create_table(
            "creative_asset_groups",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("owner_id", sa.String(50), nullable=True),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="PRIVATE"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_creative_asset_groups_tenant_name"),
        )
        op.create_index("ix_creative_asset_groups_owner_id", "creative_asset_groups", ["owner_id"])
    if "creative_asset_group_members" not in tables:
        op.create_table(
            "creative_asset_group_members",
            sa.Column("group_id", sa.String(50), nullable=False),
            sa.Column("user_id", sa.String(50), nullable=False),
            sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["group_id"], ["creative_asset_groups.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("group_id", "user_id"),
        )
    if "group_id" not in asset_columns:
        op.add_column("creative_assets", sa.Column("group_id", sa.String(50), nullable=True))
        op.create_index("ix_creative_assets_group_id", "creative_assets", ["group_id"])
        op.create_foreign_key("fk_creative_assets_group_id", "creative_assets", "creative_asset_groups", ["group_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("creative_assets")}
    if "fk_creative_assets_group_id" in foreign_keys:
        op.drop_constraint("fk_creative_assets_group_id", "creative_assets", type_="foreignkey")
    indexes = {item["name"] for item in inspector.get_indexes("creative_assets")}
    if "ix_creative_assets_group_id" in indexes:
        op.drop_index("ix_creative_assets_group_id", table_name="creative_assets")
    if "group_id" in {column["name"] for column in inspector.get_columns("creative_assets")}:
        op.drop_column("creative_assets", "group_id")
    op.drop_table("creative_asset_group_members")
    op.drop_index("ix_creative_asset_groups_owner_id", table_name="creative_asset_groups")
    op.drop_table("creative_asset_groups")
