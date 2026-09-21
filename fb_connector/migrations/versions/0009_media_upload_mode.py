"""Record the media upload path used for rollout observability."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_media_upload_mode"
down_revision: Union[str, None] = "0008_media_sha256_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    if "upload_mode" not in columns:
        op.add_column(
            "connector_media_tasks",
            sa.Column("upload_mode", sa.String(length=32), nullable=True),
        )
        op.create_index(
            "ix_connector_media_tasks_upload_mode",
            "connector_media_tasks",
            ["upload_mode"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    if "upload_mode" in columns:
        op.drop_index("ix_connector_media_tasks_upload_mode", table_name="connector_media_tasks")
        op.drop_column("connector_media_tasks", "upload_mode")
