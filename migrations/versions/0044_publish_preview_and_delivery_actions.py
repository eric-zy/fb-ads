"""Add publish preview snapshots and delivery action records."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0044_publish_preview_delivery_actions"
down_revision: Union[str, None] = "0043_shared_creative_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publish_previews",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("template_id", sa.String(length=50), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="TEMPLATE"),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("account_ids", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="READY"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_job_id", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publish_previews_id", "publish_previews", ["id"], unique=False)
    op.create_index("ix_publish_previews_created_by", "publish_previews", ["created_by"], unique=False)
    op.create_index("ix_publish_previews_template_id", "publish_previews", ["template_id"], unique=False)
    op.create_index("ix_publish_previews_snapshot_hash", "publish_previews", ["snapshot_hash"], unique=False)
    op.create_index("ix_publish_previews_submitted_job_id", "publish_previews", ["submitted_job_id"], unique=False)
    op.create_index("ix_publish_previews_tenant_created", "publish_previews", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_publish_previews_tenant_status", "publish_previews", ["tenant_id", "status"], unique=False)

    op.create_table(
        "delivery_actions",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("object_type", sa.String(length=20), nullable=False),
        sa.Column("object_id", sa.String(length=50), nullable=False),
        sa.Column("account_id", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="REQUESTED"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("before_status", sa.String(length=32), nullable=True),
        sa.Column("desired_status", sa.String(length=32), nullable=True),
        sa.Column("remote_status", sa.String(length=32), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_delivery_actions_id", "delivery_actions", ["id"], unique=False)
    op.create_index("ix_delivery_actions_object_id", "delivery_actions", ["object_id"], unique=False)
    op.create_index("ix_delivery_actions_account_id", "delivery_actions", ["account_id"], unique=False)
    op.create_index("ix_delivery_actions_requested_by", "delivery_actions", ["requested_by"], unique=False)
    op.create_index("ix_delivery_actions_task_id", "delivery_actions", ["task_id"], unique=False)
    op.create_index("ix_delivery_actions_tenant_object", "delivery_actions", ["tenant_id", "object_type", "object_id"], unique=False)
    op.create_index("ix_delivery_actions_tenant_created", "delivery_actions", ["tenant_id", "created_at"], unique=False)

    with op.batch_alter_table("campaign_jobs") as batch_op:
        batch_op.add_column(sa.Column("preview_id", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("submitted_by", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.create_index("ix_campaign_jobs_preview_id", ["preview_id"], unique=False)
        batch_op.create_index("ix_campaign_jobs_idempotency_key", ["idempotency_key"], unique=False)

    for table in ("campaign_instances", "adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("desired_status", sa.String(length=32), nullable=True))
            batch_op.add_column(sa.Column("last_synced_at", sa.DateTime(), nullable=True))
            batch_op.add_column(sa.Column("last_action_id", sa.String(length=50), nullable=True))
            batch_op.add_column(sa.Column("last_error", sa.String(length=1000), nullable=True))
            batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))

    for table in ("adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("meta_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    for table in ("adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("meta_status")
    for table in ("campaign_instances", "adset_instances", "ad_instances"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("archived_at")
            batch_op.drop_column("last_error")
            batch_op.drop_column("last_action_id")
            batch_op.drop_column("last_synced_at")
            batch_op.drop_column("desired_status")
    with op.batch_alter_table("campaign_jobs") as batch_op:
        batch_op.drop_index("ix_campaign_jobs_idempotency_key")
        batch_op.drop_index("ix_campaign_jobs_preview_id")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("submitted_at")
        batch_op.drop_column("submitted_by")
        batch_op.drop_column("preview_id")
    op.drop_index("ix_delivery_actions_tenant_created", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_tenant_object", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_task_id", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_requested_by", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_account_id", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_object_id", table_name="delivery_actions")
    op.drop_index("ix_delivery_actions_id", table_name="delivery_actions")
    op.drop_table("delivery_actions")
    op.drop_index("ix_publish_previews_tenant_status", table_name="publish_previews")
    op.drop_index("ix_publish_previews_tenant_created", table_name="publish_previews")
    op.drop_index("ix_publish_previews_submitted_job_id", table_name="publish_previews")
    op.drop_index("ix_publish_previews_snapshot_hash", table_name="publish_previews")
    op.drop_index("ix_publish_previews_template_id", table_name="publish_previews")
    op.drop_index("ix_publish_previews_created_by", table_name="publish_previews")
    op.drop_index("ix_publish_previews_id", table_name="publish_previews")
    op.drop_table("publish_previews")
