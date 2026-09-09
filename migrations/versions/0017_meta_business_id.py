"""保存 Meta 原始 BM ID，区分本地 BM 主键。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0017_meta_business_id"
down_revision: Union[str, None] = "0016_async_media_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("meta_business_id", sa.String(64), nullable=True))
    op.create_index("ix_ad_accounts_meta_business_id", "ad_accounts", ["meta_business_id"])

def downgrade() -> None:
    op.drop_index("ix_ad_accounts_meta_business_id", table_name="ad_accounts")
    op.drop_column("ad_accounts", "meta_business_id")
