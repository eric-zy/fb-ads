"""创建系统素材到 Meta 广告账户的映射表。"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_meta_asset_bindings"
down_revision: Union[str, None] = "0007_personal_ad_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("meta_asset_bindings"):
        return
    op.create_table(
        "meta_asset_bindings",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("asset_id", sa.String(length=50), nullable=False),
        sa.Column("ad_account_id", sa.String(length=50), nullable=False),
        sa.Column("meta_asset_id", sa.String(length=255), nullable=True),
        sa.Column("meta_asset_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_meta_asset_bindings_tenant"),
        sa.ForeignKeyConstraint(["asset_id"], ["creative_assets.id"], name="fk_meta_asset_bindings_asset"),
        sa.ForeignKeyConstraint(["ad_account_id"], ["ad_accounts.id"], name="fk_meta_asset_bindings_account"),
        sa.UniqueConstraint("asset_id", "ad_account_id", name="uq_meta_asset_account"),
    )
    op.create_index("ix_meta_asset_bindings_id", "meta_asset_bindings", ["id"])
    op.create_index("ix_meta_asset_bindings_asset_id", "meta_asset_bindings", ["asset_id"])
    op.create_index("ix_meta_asset_bindings_ad_account_id", "meta_asset_bindings", ["ad_account_id"])
    op.create_index("ix_meta_asset_bindings_tenant_asset", "meta_asset_bindings", ["tenant_id", "asset_id"])
    op.create_index("ix_meta_asset_bindings_tenant_account", "meta_asset_bindings", ["tenant_id", "ad_account_id"])


def downgrade() -> None:
    op.drop_index("ix_meta_asset_bindings_tenant_account", table_name="meta_asset_bindings")
    op.drop_index("ix_meta_asset_bindings_tenant_asset", table_name="meta_asset_bindings")
    op.drop_index("ix_meta_asset_bindings_ad_account_id", table_name="meta_asset_bindings")
    op.drop_index("ix_meta_asset_bindings_asset_id", table_name="meta_asset_bindings")
    op.drop_index("ix_meta_asset_bindings_id", table_name="meta_asset_bindings")
    op.drop_table("meta_asset_bindings")
