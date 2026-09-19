"""保存媒体任务入参，支持恢复丢失的 Celery 消息。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_media_task_recovery"
down_revision: Union[str, None] = "0002_delivery_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connector_media_tasks", sa.Column("credential_id", sa.String(50), nullable=True))
    op.add_column("connector_media_tasks", sa.Column("account_id", sa.String(64), nullable=True))
    op.add_column("connector_media_tasks", sa.Column("asset_type", sa.String(16), nullable=True))
    op.add_column("connector_media_tasks", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("connector_media_tasks", "source_url")
    op.drop_column("connector_media_tasks", "asset_type")
    op.drop_column("connector_media_tasks", "account_id")
    op.drop_column("connector_media_tasks", "credential_id")
