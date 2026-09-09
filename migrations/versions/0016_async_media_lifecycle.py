"""素材异步上传、去重及 Meta 处理状态字段。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0016_async_media_lifecycle"
# 0016_sinan_credentials 已经是当前主线 head，本迁移接在其后，避免产生双 head。
down_revision: Union[str, None] = "0016_sinan_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    asset_cols = {c["name"] for c in inspector.get_columns("creative_assets")}
    binding_cols = {c["name"] for c in inspector.get_columns("meta_asset_bindings")}
    for name, typ in (("sha256", sa.String(64)), ("retry_count", sa.Integer())):
        if name not in asset_cols:
            op.add_column("creative_assets", sa.Column(name, typ, nullable=True if name == "sha256" else False, server_default="0" if name == "retry_count" else None))
    for name, typ in (("retry_count", sa.Integer()), ("processing_status", sa.String(30)), ("error_code", sa.String(80))):
        if name not in binding_cols:
            op.add_column("meta_asset_bindings", sa.Column(name, typ, nullable=False if name == "retry_count" else True, server_default="0" if name == "retry_count" else None))
    try:
        op.create_index("ix_creative_assets_tenant_sha256", "creative_assets", ["tenant_id", "sha256", "asset_type"])
    except Exception:
        pass

def downgrade() -> None:
    op.drop_index("ix_creative_assets_tenant_sha256", table_name="creative_assets")
    for table, name in (("meta_asset_bindings", "error_code"), ("meta_asset_bindings", "processing_status"), ("meta_asset_bindings", "retry_count"), ("creative_assets", "retry_count"), ("creative_assets", "sha256")):
        op.drop_column(table, name)
