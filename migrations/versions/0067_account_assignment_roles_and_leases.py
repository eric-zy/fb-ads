"""Add primary/collaborator account assignment roles and operation leases."""

from alembic import op
import sqlalchemy as sa


revision = "0067_account_assignment_roles_and_leases"
down_revision = "0066_template_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_accounts",
        sa.Column(
            "assignment_role",
            sa.String(20),
            nullable=False,
            server_default="COLLABORATOR",
        ),
    )
    op.create_index(
        "ix_user_accounts_tenant_account_assignment_role",
        "user_accounts",
        ["tenant_id", "account_id", "assignment_role", "assignment_status"],
    )
    op.create_index(
        "uq_user_accounts_active_primary",
        "user_accounts",
        ["tenant_id", "account_id"],
        unique=True,
        sqlite_where=sa.text("assignment_status = 'ACTIVE' AND assignment_role = 'PRIMARY'"),
        postgresql_where=sa.text("assignment_status = 'ACTIVE' AND assignment_role = 'PRIMARY'"),
    )

    op.create_table(
        "account_operation_leases",
        sa.Column("id", sa.String(50), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.Column("account_id", sa.String(50), nullable=False),
        sa.Column("holder_user_id", sa.String(50), nullable=False),
        sa.Column("operation_type", sa.String(50), nullable=False),
        sa.Column("lease_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "account_id", name="uq_account_operation_lease_account"),
        sa.UniqueConstraint("lease_token", name="uq_account_operation_lease_token"),
    )
    op.create_index("ix_account_operation_leases_id", "account_operation_leases", ["id"])
    op.create_index(
        "ix_account_operation_leases_tenant_account",
        "account_operation_leases",
        ["tenant_id", "account_id"],
    )
    op.create_index(
        "ix_account_operation_leases_holder",
        "account_operation_leases",
        ["holder_user_id"],
    )
    op.create_index(
        "ix_account_operation_leases_expires_at",
        "account_operation_leases",
        ["expires_at"],
    )
    op.create_index(
        "ix_account_operation_lease_active",
        "account_operation_leases",
        ["tenant_id", "account_id", "expires_at"],
    )


def downgrade():
    op.drop_index("ix_account_operation_lease_active", table_name="account_operation_leases")
    op.drop_index("ix_account_operation_leases_expires_at", table_name="account_operation_leases")
    op.drop_index("ix_account_operation_leases_holder", table_name="account_operation_leases")
    op.drop_index("ix_account_operation_leases_tenant_account", table_name="account_operation_leases")
    op.drop_index("ix_account_operation_leases_id", table_name="account_operation_leases")
    op.drop_table("account_operation_leases")
    op.drop_index(
        "uq_user_accounts_active_primary",
        table_name="user_accounts",
    )
    op.drop_index(
        "ix_user_accounts_tenant_account_assignment_role",
        table_name="user_accounts",
    )
    op.drop_column("user_accounts", "assignment_role")
