"""记录 Celery 异步任务及其租户归属。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0009_async_task_records"
down_revision: Union[str, None] = "0008_meta_asset_bindings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("async_task_records"):
        return
    op.create_table("async_task_records",
        sa.Column("task_id", sa.String(100), primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32)), sa.Column("object_ids", sa.JSON),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("result_summary", sa.JSON), sa.Column("created_by", sa.String(50)),
        sa.Column("created_at", sa.DateTime), sa.Column("finished_at", sa.DateTime),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_async_task_records_tenant"),
    )
    op.create_index("ix_async_task_records_tenant_created", "async_task_records", ["tenant_id", "created_at"])

def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("async_task_records"):
        return
    op.drop_index("ix_async_task_records_tenant_created", table_name="async_task_records")
    op.drop_table("async_task_records")
