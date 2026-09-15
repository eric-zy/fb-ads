"""补充 Insights 转化动作明细和统一统计字段。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0031_insight_action_metrics"
down_revision: Union[str, None] = "0030_sync_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    fields = {
        "link_clicks": (sa.Integer(), False, "0"),
        "landing_page_views": (sa.Integer(), False, "0"),
        "leads": (sa.Integer(), False, "0"),
        "purchases": (sa.Integer(), False, "0"),
        "complete_registrations": (sa.Integer(), False, "0"),
        "conversion_value": (sa.BigInteger(), True, None),
        "actions": (sa.JSON(), True, None),
        "action_values": (sa.JSON(), True, None),
        "synced_at": (sa.DateTime(), True, None),
    }
    bind = op.get_bind()
    for table in ("account_insights", "campaign_insights", "adset_insights", "ad_insights"):
        existing = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        for name, (column, nullable, default) in fields.items():
            if name not in existing:
                op.add_column(table, sa.Column(name, column, nullable=nullable, server_default=default))


def downgrade() -> None:
    for table in ("ad_insights", "adset_insights", "campaign_insights", "account_insights"):
        for name in ("synced_at", "action_values", "actions", "conversion_value", "complete_registrations", "purchases", "leads", "landing_page_views", "link_clicks"):
            op.drop_column(table, name)
