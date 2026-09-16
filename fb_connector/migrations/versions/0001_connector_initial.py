"""Connector 初始表结构。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0001_connector_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None
def upgrade() -> None:
    op.create_table("connector_credentials", sa.Column("id", sa.String(50), primary_key=True), sa.Column("app_id", sa.String(128), nullable=False), sa.Column("access_token_encrypted", sa.Text(), nullable=False), sa.Column("token_type", sa.String(32), nullable=False, server_default="USER"), sa.Column("meta_user_id", sa.String(64)), sa.Column("scopes", sa.JSON()), sa.Column("expires_at", sa.DateTime()), sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"), sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("connector_media_tasks", sa.Column("task_id", sa.String(50), primary_key=True), sa.Column("media_id", sa.String(64), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True), sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"), sa.Column("meta_asset_id", sa.String(128)), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("connector_delivery_tasks", sa.Column("task_id", sa.String(50), primary_key=True), sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True), sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"), sa.Column("step", sa.String(32), nullable=False, server_default="QUEUED"), sa.Column("campaign_id", sa.String(128)), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
def downgrade() -> None:
    op.drop_table("connector_delivery_tasks"); op.drop_table("connector_media_tasks"); op.drop_table("connector_credentials")
