"""add unified Meta OAuth connection ownership"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_meta_connections"
down_revision: Union[str, None] = "0014_meta_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meta_connections",
        sa.Column("id", sa.String(50), nullable=False),
        sa.Column("meta_user_id", sa.String(64), nullable=False),
        sa.Column("app_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("authorized_by_user_id", sa.String(50), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "meta_user_id", "app_id", name="uq_meta_connections_user_app"),
    )
    op.create_index("ix_meta_connections_id", "meta_connections", ["id"], unique=False)
    op.create_index("ix_meta_connections_meta_user_id", "meta_connections", ["meta_user_id"], unique=False)
    op.create_index("ix_meta_connections_tenant_status", "meta_connections", ["tenant_id", "status"], unique=False)

    op.add_column("credentials", sa.Column("connection_id", sa.String(50), nullable=True))
    op.create_foreign_key("fk_credentials_connection", "credentials", "meta_connections", ["connection_id"], ["id"])
    op.create_index("ix_credentials_connection_id", "credentials", ["connection_id"], unique=False)

    for table in ("meta_accounts", "ad_accounts", "meta_pages"):
        op.add_column(table, sa.Column("connection_id", sa.String(50), nullable=True))
        op.create_foreign_key(f"fk_{table}_connection", table, "meta_connections", ["connection_id"], ["id"])
        op.create_index(f"ix_{table}_connection_id", table, ["connection_id"], unique=False)


def downgrade() -> None:
    for table in ("meta_pages", "ad_accounts", "meta_accounts", "credentials"):
        op.drop_index(f"ix_{table}_connection_id", table_name=table)
        op.drop_constraint(f"fk_{table}_connection", table, type_="foreignkey")
        op.drop_column(table, "connection_id")
    op.drop_index("ix_meta_connections_tenant_status", table_name="meta_connections")
    op.drop_index("ix_meta_connections_meta_user_id", table_name="meta_connections")
    op.drop_index("ix_meta_connections_id", table_name="meta_connections")
    op.drop_table("meta_connections")
