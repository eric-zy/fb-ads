"""保存海外投放入参，支持恢复丢失的 Celery 消息。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_delivery_task_recovery"
down_revision: Union[str, None] = "0002_media_task_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("connector_delivery_tasks", sa.Column("source_task_id", sa.String(64), nullable=True))
    op.add_column("connector_delivery_tasks", sa.Column("credential_id", sa.String(50), nullable=True))
    op.add_column("connector_delivery_tasks", sa.Column("account_id", sa.String(64), nullable=True))
    op.add_column("connector_delivery_tasks", sa.Column("request_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("connector_delivery_tasks", "request_payload")
    op.drop_column("connector_delivery_tasks", "account_id")
    op.drop_column("connector_delivery_tasks", "credential_id")
    op.drop_column("connector_delivery_tasks", "source_task_id")
