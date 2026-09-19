"""Add recoverable delete timestamps for published delivery objects."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0045_delivery_soft_delete_drift"
down_revision: Union[str, None] = "0044_publish_preview_delivery_actions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("campaign_instances", "adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in ("campaign_instances", "adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("deleted_at")
