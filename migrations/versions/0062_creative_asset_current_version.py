"""Add current version marker for creative assets."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0062_creative_asset_current_version"
down_revision: Union[str, None] = "0061_creative_asset_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("creative_assets")}
    if "is_current" not in columns:
        op.add_column("creative_assets", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))

def downgrade() -> None:
    op.drop_column("creative_assets", "is_current")
