"""Classify BM ad accounts as owned or client assets."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0020_ad_account_asset_type"
down_revision: Union[str, None] = "0019_account_payment_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ad_accounts",
        sa.Column("asset_type", sa.String(20), nullable=False, server_default="OWNED"),
    )
    op.create_index("ix_ad_accounts_tenant_asset_type", "ad_accounts", ["tenant_id", "asset_type"])


def downgrade() -> None:
    op.drop_index("ix_ad_accounts_tenant_asset_type", table_name="ad_accounts")
    op.drop_column("ad_accounts", "asset_type")
