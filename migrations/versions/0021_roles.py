"""Add tenant-scoped role templates."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0021_roles"
down_revision: Union[str, None] = "0020_ad_account_asset_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),
    )
    op.create_index("ix_roles_tenant_created", "roles", ["tenant_id", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_roles_tenant_created", table_name="roles")
    op.drop_table("roles")
