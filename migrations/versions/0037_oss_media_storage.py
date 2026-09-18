"""Add OSS media metadata and upload sessions."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0037_oss_media_storage"
down_revision: Union[str, None] = "0036_page_connector_ref"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ASSET_COLUMNS = (
    ("original_name", sa.String(255)),
    ("stored_name", sa.String(255)),
    ("object_key", sa.String(1024)),
    ("storage_bucket", sa.String(128)),
    ("storage_region", sa.String(64)),
    ("storage_status", sa.String(20)),
    ("processing_status", sa.String(20)),
    ("thumbnail_key", sa.String(1024)),
    ("cover_key", sa.String(1024)),
    ("md5", sa.String(32)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("creative_assets")}
    for name, column_type in ASSET_COLUMNS:
        if name not in existing:
            op.add_column("creative_assets", sa.Column(name, column_type, nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("creative_assets")}
    if "ix_creative_assets_tenant_md5" not in indexes:
        op.create_index("ix_creative_assets_tenant_md5", "creative_assets", ["tenant_id", "md5"])
    if "ix_creative_assets_tenant_object_key" not in indexes:
        op.create_index("ix_creative_assets_tenant_object_key", "creative_assets", ["tenant_id", "object_key"])

    tables = {table_name for table_name in inspector.get_table_names()}
    if "media_upload_sessions" not in tables:
        op.create_table(
            "media_upload_sessions",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("asset_id", sa.String(50), nullable=False),
            sa.Column("object_key", sa.String(1024), nullable=False),
            sa.Column("upload_id", sa.String(255), nullable=True),
            sa.Column("expected_size", sa.Integer(), nullable=True),
            sa.Column("expected_md5", sa.String(32), nullable=True),
            sa.Column("expected_sha256", sa.String(64), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="INIT"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    session_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("media_upload_sessions")}
    if "ix_media_upload_sessions_tenant_status" not in session_indexes:
        op.create_index("ix_media_upload_sessions_tenant_status", "media_upload_sessions", ["tenant_id", "status"])
    if "ix_media_upload_sessions_tenant_hash" not in session_indexes:
        op.create_index("ix_media_upload_sessions_tenant_hash", "media_upload_sessions", ["tenant_id", "expected_sha256", "expected_size"])


def downgrade() -> None:
    op.drop_index("ix_media_upload_sessions_tenant_hash", table_name="media_upload_sessions")
    op.drop_index("ix_media_upload_sessions_tenant_status", table_name="media_upload_sessions")
    op.drop_table("media_upload_sessions")
    op.drop_index("ix_creative_assets_tenant_object_key", table_name="creative_assets")
    op.drop_index("ix_creative_assets_tenant_md5", table_name="creative_assets")
    for name, _ in reversed(ASSET_COLUMNS):
        op.drop_column("creative_assets", name)
