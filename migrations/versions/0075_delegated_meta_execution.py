"""Explicit Meta execution delegation on an account assignment."""
from alembic import op
import sqlalchemy as sa

revision = "0075_delegated_meta_execution"
down_revision = "0074_personal_meta_authorization"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_accounts", sa.Column("execution_connection_id", sa.String(50), nullable=True))
    op.add_column("user_accounts", sa.Column("execution_granted_by", sa.String(50), nullable=True))
    op.add_column("user_accounts", sa.Column("execution_granted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_user_accounts_execution_connection_id", "user_accounts", ["execution_connection_id"])
    # Existing assignments deliberately retain personal execution until an admin chooses.


def downgrade():
    op.drop_index("ix_user_accounts_execution_connection_id", table_name="user_accounts")
    for column in ("execution_granted_at", "execution_granted_by", "execution_connection_id"):
        op.drop_column("user_accounts", column)
