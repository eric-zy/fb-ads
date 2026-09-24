"""Add creative asset version chains."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0061_creative_asset_versions"
down_revision: Union[str, None] = "0060_creative_asset_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("creative_assets")}
    if "version_group_id" not in columns:
        op.add_column("creative_assets", sa.Column("version_group_id", sa.String(50), nullable=True))
    if "version_number" not in columns:
        op.add_column("creative_assets", sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"))
    if "previous_version_id" not in columns:
        op.add_column("creative_assets", sa.Column("previous_version_id", sa.String(50), nullable=True))
    op.execute(sa.text("UPDATE creative_assets SET version_group_id = id WHERE version_group_id IS NULL"))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("creative_assets")}
    if "ix_creative_assets_version_group" not in indexes:
        op.create_index("ix_creative_assets_version_group", "creative_assets", ["version_group_id"])
    if "ix_creative_assets_previous_version" not in indexes:
        op.create_index("ix_creative_assets_previous_version", "creative_assets", ["previous_version_id"])

def downgrade() -> None:
    op.drop_index("ix_creative_assets_previous_version", table_name="creative_assets")
    op.drop_index("ix_creative_assets_version_group", table_name="creative_assets")
    op.drop_column("creative_assets", "previous_version_id")
    op.drop_column("creative_assets", "version_number")
    op.drop_column("creative_assets", "version_group_id")
