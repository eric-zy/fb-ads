"""增加洞察业务收入、利润与 ROI 字段。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0011_insight_business_metrics"
down_revision: Union[str, None] = "0010_adset_insights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    for table in ("account_insights", "campaign_insights", "adset_insights", "ad_insights"):
        columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        if "revenue" not in columns: op.add_column(table, sa.Column("revenue", sa.BigInteger(), nullable=True))
        if "profit" not in columns: op.add_column(table, sa.Column("profit", sa.BigInteger(), nullable=True))
        if "roi" not in columns: op.add_column(table, sa.Column("roi", sa.Float(), nullable=True))
def downgrade() -> None:
    for table in ("ad_insights", "adset_insights", "campaign_insights", "account_insights"):
        op.drop_column(table, "roi"); op.drop_column(table, "profit"); op.drop_column(table, "revenue")
