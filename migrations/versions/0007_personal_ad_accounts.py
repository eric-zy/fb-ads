"""允许个人 OAuth 直接接入广告账户，不强制关联 BM。"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_personal_ad_accounts"
down_revision: Union[str, None] = "0006_multi_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("credential_id", sa.String(length=50), nullable=True))
    op.add_column("ad_accounts", sa.Column("owner_type", sa.String(length=20), nullable=True))
    op.create_index("ix_ad_accounts_credential_id", "ad_accounts", ["credential_id"])
    op.create_foreign_key(
        "fk_ad_accounts_credential_id", "ad_accounts", "credentials", ["credential_id"], ["id"]
    )
    op.execute("UPDATE ad_accounts SET owner_type = CASE WHEN business_id IS NULL THEN 'PERSONAL' ELSE 'BUSINESS' END")
    op.alter_column("ad_accounts", "owner_type", nullable=False, server_default="BUSINESS")
    op.drop_constraint("uq_business_account", "ad_accounts", type_="unique")
    op.alter_column("ad_accounts", "business_id", existing_type=sa.String(length=50), nullable=True)
    op.create_unique_constraint("uq_business_account", "ad_accounts", ["business_id", "account_id"])


def downgrade() -> None:
    op.drop_constraint("uq_business_account", "ad_accounts", type_="unique")
    # 个人账户无法安全回填 BM，回滚前必须由管理员完成归属补全。
    op.alter_column("ad_accounts", "business_id", existing_type=sa.String(length=50), nullable=False)
    op.create_unique_constraint("uq_business_account", "ad_accounts", ["business_id", "account_id"])
    op.drop_constraint("fk_ad_accounts_credential_id", "ad_accounts", type_="foreignkey")
    op.drop_index("ix_ad_accounts_credential_id", table_name="ad_accounts")
    op.drop_column("ad_accounts", "owner_type")
    op.drop_column("ad_accounts", "credential_id")
