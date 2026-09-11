"""Add tenant account groups."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0023_account_groups"
down_revision: Union[str, None] = "0022_user_role_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "account_groups" not in tables:
        op.create_table("account_groups", sa.Column("id", sa.String(50), primary_key=True), sa.Column("tenant_id", sa.String(50), nullable=False), sa.Column("name", sa.String(128), nullable=False), sa.Column("description", sa.String(500)), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime()), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]), sa.UniqueConstraint("tenant_id", "name", name="uq_account_groups_tenant_name"))
    indexes = {index["name"] for index in inspector.get_indexes("account_groups")} if "account_groups" in tables else set()
    if "ix_account_groups_tenant" not in indexes:
        op.create_index("ix_account_groups_tenant", "account_groups", ["tenant_id"])
    if "account_group_accounts" not in tables:
        op.create_table("account_group_accounts", sa.Column("group_id", sa.String(50), nullable=False), sa.Column("account_id", sa.String(50), nullable=False), sa.ForeignKeyConstraint(["group_id"], ["account_groups.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["account_id"], ["ad_accounts.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("group_id", "account_id"))
    if "account_group_users" not in tables:
        op.create_table("account_group_users", sa.Column("group_id", sa.String(50), nullable=False), sa.Column("user_id", sa.String(50), nullable=False), sa.ForeignKeyConstraint(["group_id"], ["account_groups.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("group_id", "user_id"))
def downgrade() -> None:
    op.drop_table("account_group_users"); op.drop_table("account_group_accounts"); op.drop_index("ix_account_groups_tenant", table_name="account_groups"); op.drop_table("account_groups")
