"""Carry the source MD5 into Connector media tasks for local cache reuse."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_media_content_cache"
down_revision: Union[str, None] = "0005_callback_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    if "expected_md5" not in columns:
        op.add_column(
            "connector_media_tasks",
            sa.Column("expected_md5", sa.String(length=32), nullable=True),
        )
        op.create_index(
            "ix_connector_media_tasks_expected_md5",
            "connector_media_tasks",
            ["expected_md5"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_connector_media_tasks_expected_md5",
        table_name="connector_media_tasks",
    )
    op.drop_column("connector_media_tasks", "expected_md5")
