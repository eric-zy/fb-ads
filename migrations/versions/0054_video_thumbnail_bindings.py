"""Store account-scoped Meta thumbnail hashes for video assets."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0054_video_thumbnail_bindings"
down_revision: Union[str, None] = "0053_campaign_job_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("meta_asset_bindings")}
    if "meta_thumbnail_hash" not in columns:
        op.add_column(
            "meta_asset_bindings",
            sa.Column("meta_thumbnail_hash", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("meta_asset_bindings")}
    if "meta_thumbnail_hash" in columns:
        op.drop_column("meta_asset_bindings", "meta_thumbnail_hash")
