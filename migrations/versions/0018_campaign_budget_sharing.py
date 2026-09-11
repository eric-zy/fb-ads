"""Add explicit Meta campaign budget sharing flag."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0018_campaign_budget_sharing"
down_revision: Union[str, None] = "0017_meta_business_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # 兼容历史环境：部分数据库曾通过初始化脚本/手工变更提前创建该字段，
    # 但 alembic_version 仍停留在 0017。迁移只在字段不存在时新增，随后仍会
    # 正常写入 0018 版本并继续执行后续迁移。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("campaign_templates")}
    if "is_adset_budget_sharing_enabled" not in columns:
        op.add_column(
            "campaign_templates",
            sa.Column("is_adset_budget_sharing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )

def downgrade() -> None:
    op.drop_column("campaign_templates", "is_adset_budget_sharing_enabled")
