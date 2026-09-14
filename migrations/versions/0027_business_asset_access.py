"""Add tenant-unique ad accounts and BM asset access relations."""
from typing import Sequence, Union
import uuid
from alembic import op
import sqlalchemy as sa

revision: str = "0027_business_asset_access"
down_revision: Union[str, None] = "0026_creative_asset_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    if "business_asset_access" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "business_asset_access",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("business_id", sa.String(50), sa.ForeignKey("meta_accounts.id"), nullable=False),
            sa.Column("asset_type", sa.String(32), nullable=False, server_default="AD_ACCOUNT"),
            sa.Column("asset_id", sa.String(50), sa.ForeignKey("ad_accounts.id"), nullable=False),
            sa.Column("access_level", sa.String(32), nullable=False, server_default="READ"),
            sa.Column("access_source", sa.String(32), nullable=False, server_default="PARTNER"),
            sa.Column("credential_id", sa.String(50), sa.ForeignKey("credentials.id")),
            sa.Column("meta_tasks", sa.Text()), sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
            sa.Column("last_verified_at", sa.DateTime()), sa.Column("last_error", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("tenant_id", "business_id", "asset_type", "asset_id", name="uq_business_asset_access"),
        )
        op.create_index("ix_asset_access_tenant_business", "business_asset_access", ["tenant_id", "business_id"])
        op.create_index("ix_asset_access_tenant_asset", "business_asset_access", ["tenant_id", "asset_type", "asset_id"])
    # 旧模型每条账户记录代表一个 BM 访问关系，先迁移关系数据。
    for row in bind.execute(sa.text("SELECT id, tenant_id, business_id, asset_type, created_at, updated_at FROM ad_accounts WHERE business_id IS NOT NULL")).mappings():
        exists = bind.execute(sa.text("SELECT 1 FROM business_asset_access WHERE tenant_id=:t AND business_id=:b AND asset_type='AD_ACCOUNT' AND asset_id=:a"), {"t": row["tenant_id"], "b": row["business_id"], "a": row["id"]}).first()
        if not exists:
            bind.execute(sa.text("INSERT INTO business_asset_access (id,tenant_id,business_id,asset_type,asset_id,access_level,access_source,status,created_at,updated_at) VALUES (:id,:t,:b,'AD_ACCOUNT',:a,'MANAGE',:source,'ACTIVE',:c,:u)"), {"id": uuid.uuid4().hex, "t": row["tenant_id"], "b": row["business_id"], "a": row["id"], "source": row["asset_type"] or "PARTNER", "c": row["created_at"], "u": row["updated_at"]})
    # 先删除旧唯一约束，再按租户+Meta账户建立主实体唯一性。
    try:
        op.drop_constraint("uq_business_account", "ad_accounts", type_="unique")
    except Exception:
        pass
    op.create_unique_constraint("uq_tenant_ad_account", "ad_accounts", ["tenant_id", "account_id"])

def downgrade() -> None:
    op.drop_constraint("uq_tenant_ad_account", "ad_accounts", type_="unique")
    op.create_unique_constraint("uq_business_account", "ad_accounts", ["business_id", "account_id"])
    op.drop_table("business_asset_access")
