"""add tenant-scoped Meta Pages"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_meta_pages"
down_revision: Union[str, None] = "0013_repair_credential_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_pages",
        sa.Column("id", sa.String(50), nullable=False),
        sa.Column("page_id", sa.String(64), nullable=False),
        sa.Column("page_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("tasks", sa.JSON(), nullable=True),
        sa.Column("credential_id", sa.String(50), nullable=False),
        sa.Column("page_access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "page_id", name="uq_meta_pages_tenant_page"),
    )
    op.create_index("ix_meta_pages_id", "meta_pages", ["id"], unique=False)
    op.create_index("ix_meta_pages_credential_id", "meta_pages", ["credential_id"], unique=False)
    op.create_index("ix_meta_pages_tenant_id", "meta_pages", ["tenant_id"], unique=False)
    op.create_index("ix_meta_pages_tenant_status", "meta_pages", ["tenant_id", "status"], unique=False)
    op.create_index("ix_meta_pages_tenant_credential", "meta_pages", ["tenant_id", "credential_id"], unique=False)


def downgrade() -> None:
    op.drop_table("meta_pages")
