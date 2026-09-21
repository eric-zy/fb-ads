"""Use SHA256 as the primary connector media cache key."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_media_sha256_cache"
down_revision: Union[str, None] = "0007_video_thumbnail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    if "expected_sha256" not in columns:
        op.add_column(
            "connector_media_tasks",
            sa.Column("expected_sha256", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_connector_media_tasks_expected_sha256",
            "connector_media_tasks",
            ["expected_sha256"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    if "expected_sha256" in columns:
        op.drop_index("ix_connector_media_tasks_expected_sha256", table_name="connector_media_tasks")
        op.drop_column("connector_media_tasks", "expected_sha256")
