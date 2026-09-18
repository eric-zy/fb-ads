"""Make creative assets shared within a tenant."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0043_shared_creative_assets"
down_revision: Union[str, None] = "0042_creative_asset_usage_account_daily_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 历史数据也统一为租户共享，避免接口已放开但返回值仍显示旧权限语义。
    op.execute(
        sa.text(
            "UPDATE creative_assets SET visibility = 'TENANT' "
            "WHERE visibility IS NULL OR visibility <> 'TENANT'"
        )
    )
    with op.batch_alter_table("creative_assets") as batch_op:
        batch_op.alter_column(
            "visibility",
            existing_type=sa.String(length=20),
            server_default="TENANT",
            existing_nullable=False,
        )


def downgrade() -> None:
    # 不将数据重新标记为 ACCOUNT，避免回滚后产生用户不可见素材；仅恢复数据库默认值。
    with op.batch_alter_table("creative_assets") as batch_op:
        batch_op.alter_column(
            "visibility",
            existing_type=sa.String(length=20),
            server_default="ACCOUNT",
            existing_nullable=False,
        )
