"""Bind users to tenant role templates."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0022_user_role_binding"
down_revision: Union[str, None] = "0021_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("users", sa.Column("role_id", sa.String(50), nullable=True))
    op.create_index("ix_users_role_id", "users", ["role_id"])
    op.create_foreign_key("fk_users_role_id", "users", "roles", ["role_id"], ["id"], ondelete="SET NULL")

def downgrade() -> None:
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_column("users", "role_id")
