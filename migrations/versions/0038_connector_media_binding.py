"""Track asynchronous Connector media upload tasks."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0038_connector_media_binding"
down_revision: Union[str, None] = "0037_oss_media_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("meta_asset_bindings")}
    if "connector_task_id" not in columns:
        op.add_column("meta_asset_bindings", sa.Column("connector_task_id", sa.String(100), nullable=True))
        op.create_index("ix_meta_asset_bindings_connector_task_id", "meta_asset_bindings", ["connector_task_id"])


def downgrade() -> None:
    op.drop_index("ix_meta_asset_bindings_connector_task_id", table_name="meta_asset_bindings")
    op.drop_column("meta_asset_bindings", "connector_task_id")
