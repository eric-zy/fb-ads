"""新增广告组级别洞察表。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0010_adset_insights"
down_revision: Union[str, None] = "0009_async_task_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("adset_insights"):
        return
    op.create_table("adset_insights", sa.Column("id", sa.String(50), primary_key=True), sa.Column("tenant_id", sa.String(50), nullable=False), sa.Column("ad_group_id", sa.String(50), nullable=False), sa.Column("date", sa.Date, nullable=False), sa.Column("spend", sa.BigInteger, server_default="0"), sa.Column("impressions", sa.Integer, server_default="0"), sa.Column("clicks", sa.Integer, server_default="0"), sa.Column("conversions", sa.Integer, server_default="0"), sa.Column("ctr", sa.Float, server_default="0"), sa.Column("cpc", sa.Float, server_default="0"), sa.Column("cpm", sa.Float, server_default="0"), sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]), sa.ForeignKeyConstraint(["ad_group_id"], ["ad_groups.id"]))
    op.create_index("ix_adset_insights_group_date", "adset_insights", ["ad_group_id", "date"])
    op.create_index("ix_adset_insights_tenant_group_date", "adset_insights", ["tenant_id", "ad_group_id", "date"])
def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("adset_insights"):
        return
    op.drop_index("ix_adset_insights_tenant_group_date", table_name="adset_insights"); op.drop_index("ix_adset_insights_group_date", table_name="adset_insights"); op.drop_table("adset_insights")
