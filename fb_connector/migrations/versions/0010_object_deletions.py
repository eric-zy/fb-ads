"""Persist receipts for explicit Meta object deletion."""
from alembic import op
import sqlalchemy as sa

revision = "0010_object_deletions"
down_revision = "0009_media_upload_mode"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "connector_object_deletions",
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("object_id", sa.String(128), nullable=False),
        sa.Column("credential_id", sa.String(50), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("connector_object_deletions")
