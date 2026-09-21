"""Persist video cover URL and uploaded Meta thumbnail hash."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_video_thumbnail"
down_revision: Union[str, None] = "0006_media_content_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("connector_media_tasks")}
    if "cover_url" not in columns:
        op.add_column("connector_media_tasks", sa.Column("cover_url", sa.Text(), nullable=True))
    if "meta_thumbnail_hash" not in columns:
        op.add_column(
            "connector_media_tasks",
            sa.Column("meta_thumbnail_hash", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("connector_media_tasks")}
    if "meta_thumbnail_hash" in columns:
        op.drop_column("connector_media_tasks", "meta_thumbnail_hash")
    if "cover_url" in columns:
        op.drop_column("connector_media_tasks", "cover_url")
