"""为已存在的 Insights 表补充数据同步时间。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0032_insight_sync_timestamp"
down_revision: Union[str, None] = "0031_insight_action_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in ("account_insights", "campaign_insights", "adset_insights", "ad_insights"):
        columns = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        if "synced_at" not in columns:
            op.add_column(table, sa.Column("synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in ("ad_insights", "adset_insights", "campaign_insights", "account_insights"):
        op.drop_column(table, "synced_at")
