"""Persist Connector callback events for retryable SaaS delivery."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_callback_events"
down_revision: Union[str, None] = "0004_resumable_media_upload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_callback_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("callback_path", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_connector_callback_events_task_id", "connector_callback_events", ["task_id"], unique=False)
    op.create_index("ix_connector_callback_events_status", "connector_callback_events", ["status"], unique=False)
    op.create_index("ix_connector_callback_events_next_retry_at", "connector_callback_events", ["next_retry_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_connector_callback_events_next_retry_at", table_name="connector_callback_events")
    op.drop_index("ix_connector_callback_events_status", table_name="connector_callback_events")
    op.drop_index("ix_connector_callback_events_task_id", table_name="connector_callback_events")
    op.drop_table("connector_callback_events")
