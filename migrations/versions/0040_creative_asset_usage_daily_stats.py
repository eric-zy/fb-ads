"""Add rebuildable daily aggregates for creative asset usage."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0040_creative_asset_usage_daily_stats"
down_revision: Union[str, None] = "0039_creative_asset_usage_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "creative_asset_usage_daily_stats" not in set(inspector.get_table_names()):
        op.create_table(
            "creative_asset_usage_daily_stats",
            sa.Column("id", sa.String(150), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("asset_id", sa.String(50), nullable=False),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("successful_usage_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_usage_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tenant_id", "asset_id", "stat_date", name="uq_asset_usage_daily_stat"),
        )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("creative_asset_usage_daily_stats")}
    for name, columns in (
        ("ix_creative_asset_usage_daily_stats_id", ["id"]),
        ("ix_creative_asset_usage_daily_stats_asset_id", ["asset_id"]),
        ("ix_creative_asset_usage_daily_stats_stat_date", ["stat_date"]),
        ("ix_asset_usage_daily_stats_tenant_date", ["tenant_id", "stat_date"]),
        ("ix_asset_usage_daily_stats_tenant_asset_date", ["tenant_id", "asset_id", "stat_date"]),
    ):
        if name not in indexes:
            op.create_index(name, "creative_asset_usage_daily_stats", columns)

    # 初次上线回填历史事件，后续由 Celery 任务增量重算最近几天。
    op.execute(
        sa.text(
            """
            INSERT INTO creative_asset_usage_daily_stats
                (id, tenant_id, asset_id, stat_date, usage_count,
                 successful_usage_count, failed_usage_count, last_used_at, updated_at)
            SELECT
                'daily-' || e.tenant_id || '-' || e.asset_id || '-' || CAST(DATE(e.occurred_at) AS VARCHAR),
                e.tenant_id,
                e.asset_id,
                DATE(e.occurred_at),
                COUNT(*),
                SUM(CASE WHEN e.status = 'SUCCESS' THEN 1 ELSE 0 END),
                SUM(CASE WHEN e.status = 'FAILED' THEN 1 ELSE 0 END),
                MAX(e.occurred_at),
                CURRENT_TIMESTAMP
            FROM creative_asset_usage_events e
            GROUP BY e.tenant_id, e.asset_id, DATE(e.occurred_at)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_asset_usage_daily_stats_tenant_asset_date", table_name="creative_asset_usage_daily_stats")
    op.drop_index("ix_asset_usage_daily_stats_tenant_date", table_name="creative_asset_usage_daily_stats")
    op.drop_index("ix_creative_asset_usage_daily_stats_stat_date", table_name="creative_asset_usage_daily_stats")
    op.drop_index("ix_creative_asset_usage_daily_stats_asset_id", table_name="creative_asset_usage_daily_stats")
    op.drop_index("ix_creative_asset_usage_daily_stats_id", table_name="creative_asset_usage_daily_stats")
    op.drop_table("creative_asset_usage_daily_stats")
