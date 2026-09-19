"""Persist the overseas Connector task id for delivery callbacks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0046_connector_callback_task_id"
down_revision: Union[str, None] = "0045_delivery_soft_delete_drift"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("campaign_job_items")}
    if "connector_task_id" not in columns:
        op.add_column("campaign_job_items", sa.Column("connector_task_id", sa.String(length=64), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("campaign_job_items")}
    if "ix_campaign_job_items_connector_task_id" not in indexes:
        op.create_index("ix_campaign_job_items_connector_task_id", "campaign_job_items", ["connector_task_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("campaign_job_items")}
    if "ix_campaign_job_items_connector_task_id" in indexes:
        op.drop_index("ix_campaign_job_items_connector_task_id", table_name="campaign_job_items")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("campaign_job_items")}
    if "connector_task_id" in columns:
        op.drop_column("campaign_job_items", "connector_task_id")
