"""Track creative asset usage for future statistics."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0039_creative_asset_usage_events"
down_revision: Union[str, None] = "0038_connector_media_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "creative_asset_usage_events" not in tables:
        op.create_table(
            "creative_asset_usage_events",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("event_key", sa.String(150), nullable=False),
            sa.Column("asset_id", sa.String(50), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False, server_default="PUBLISH"),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("publish_task_id", sa.String(50), nullable=True),
            sa.Column("published_ad_id", sa.String(50), nullable=True),
            sa.Column("ad_account_id", sa.String(50), nullable=True),
            sa.Column("actor_id", sa.String(50), nullable=True),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "event_key", name="uq_asset_usage_event_key"),
        )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("creative_asset_usage_events")}
    for name, columns in (
        ("ix_creative_asset_usage_events_id", ["id"]),
        ("ix_creative_asset_usage_events_event_key", ["event_key"]),
        ("ix_creative_asset_usage_events_asset_id", ["asset_id"]),
        ("ix_creative_asset_usage_events_publish_task_id", ["publish_task_id"]),
        ("ix_creative_asset_usage_events_published_ad_id", ["published_ad_id"]),
        ("ix_creative_asset_usage_events_ad_account_id", ["ad_account_id"]),
        ("ix_creative_asset_usage_events_actor_id", ["actor_id"]),
        ("ix_creative_asset_usage_events_occurred_at", ["occurred_at"]),
        ("ix_asset_usage_events_tenant_asset_time", ["tenant_id", "asset_id", "occurred_at"]),
        ("ix_asset_usage_events_tenant_account_time", ["tenant_id", "ad_account_id", "occurred_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "creative_asset_usage_events", columns)

    # 将已有批量发布结果迁移为历史事件，使新旧统计口径连续。
    op.execute(
        sa.text(
            """
            INSERT INTO creative_asset_usage_events
                (id, tenant_id, event_key, asset_id, event_type, status,
                 publish_task_id, published_ad_id, ad_account_id, external_id,
                 error_message, occurred_at, created_at)
            SELECT
                'legacy-' || pa.id,
                pa.tenant_id,
                'LEGACY:PUBLISH:' || pa.id,
                pa.asset_id,
                'PUBLISH',
                CASE WHEN pa.status = 'success' THEN 'SUCCESS' ELSE 'FAILED' END,
                pa.task_id,
                pa.id,
                pa.account_id,
                COALESCE(pa.fb_ad_id, pa.fb_campaign_id),
                pa.error,
                pa.created_at,
                pa.created_at
            FROM published_ads pa
            WHERE pa.asset_id IS NOT NULL
              AND pa.tenant_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM creative_asset_usage_events e
                  WHERE e.tenant_id = pa.tenant_id
                    AND e.event_key = 'LEGACY:PUBLISH:' || pa.id
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_asset_usage_events_tenant_account_time", table_name="creative_asset_usage_events")
    op.drop_index("ix_asset_usage_events_tenant_asset_time", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_occurred_at", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_actor_id", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_ad_account_id", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_published_ad_id", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_publish_task_id", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_asset_id", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_event_key", table_name="creative_asset_usage_events")
    op.drop_index("ix_creative_asset_usage_events_id", table_name="creative_asset_usage_events")
    op.drop_table("creative_asset_usage_events")
