"""Persist Meta resumable video upload checkpoints."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_resumable_media_upload"
down_revision: Union[str, None] = "0003_delivery_task_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = (
    ("phase", sa.String(32)),
    ("total_bytes", sa.Integer()),
    ("uploaded_bytes", sa.Integer()),
    ("upload_session_id", sa.String(128)),
    ("meta_video_id", sa.String(128)),
    ("start_offset", sa.Integer()),
    ("end_offset", sa.Integer()),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("connector_media_tasks")}
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column("connector_media_tasks", sa.Column(name, column_type, nullable=True))
    op.execute(
        sa.text(
            "UPDATE connector_media_tasks "
            "SET phase = CASE "
            "WHEN status = 'SUCCESS' THEN 'READY' "
            "WHEN status = 'FAILED' THEN 'FAILED' "
            "ELSE 'QUEUED' END "
            "WHERE phase IS NULL"
        )
    )


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("connector_media_tasks", name)
