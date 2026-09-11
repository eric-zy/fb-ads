"""Add creator and visibility fields for creative asset access control."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0024_creative_asset_access"
down_revision: Union[str, None] = "0023_account_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("creative_assets")}
    if "created_by" not in columns:
        op.add_column("creative_assets", sa.Column("created_by", sa.String(50), nullable=True))
        op.create_index("ix_creative_assets_created_by", "creative_assets", ["created_by"])
        op.create_foreign_key("fk_creative_assets_created_by", "creative_assets", "users", ["created_by"], ["id"], ondelete="SET NULL")
    if "visibility" not in columns:
        op.add_column("creative_assets", sa.Column("visibility", sa.String(20), nullable=False, server_default="ACCOUNT"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("creative_assets")}
    if "fk_creative_assets_created_by" in foreign_keys:
        op.drop_constraint("fk_creative_assets_created_by", "creative_assets", type_="foreignkey")
    indexes = {item["name"] for item in inspector.get_indexes("creative_assets")}
    if "ix_creative_assets_created_by" in indexes:
        op.drop_index("ix_creative_assets_created_by", table_name="creative_assets")
    columns = {column["name"] for column in inspector.get_columns("creative_assets")}
    if "visibility" in columns:
        op.drop_column("creative_assets", "visibility")
    if "created_by" in columns:
        op.drop_column("creative_assets", "created_by")
