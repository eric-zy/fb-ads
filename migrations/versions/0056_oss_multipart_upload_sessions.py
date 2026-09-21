"""Store browser OSS multipart upload parameters."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0056_oss_multipart_upload_sessions"
down_revision: Union[str, None] = "0055_meta_audience_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("media_upload_sessions")}
    if "upload_mode" not in columns:
        op.add_column(
            "media_upload_sessions",
            sa.Column("upload_mode", sa.String(length=20), nullable=False, server_default="single"),
        )
    if "part_size" not in columns:
        op.add_column("media_upload_sessions", sa.Column("part_size", sa.Integer(), nullable=True))
    if "part_count" not in columns:
        op.add_column("media_upload_sessions", sa.Column("part_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("media_upload_sessions")}
    for name in ("part_count", "part_size", "upload_mode"):
        if name in columns:
            op.drop_column("media_upload_sessions", name)
