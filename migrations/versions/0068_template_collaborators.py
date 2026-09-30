"""Add tenant-scoped campaign template collaboration access."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0068_template_collaborators"
down_revision: Union[str, None] = "0067_account_assignment_roles_and_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "template_collaborators",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("template_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="VIEWER"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("granted_by", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["campaign_templates.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "template_id", "user_id", name="uq_template_collaborator"),
    )
    op.create_index("ix_template_collaborators_id", "template_collaborators", ["id"])
    op.create_index("ix_template_collaborators_template_id", "template_collaborators", ["template_id"])
    op.create_index("ix_template_collaborators_user_id", "template_collaborators", ["user_id"])
    op.create_index(
        "ix_template_collaborators_tenant_template_status",
        "template_collaborators",
        ["tenant_id", "template_id", "status"],
    )
    op.create_index(
        "ix_template_collaborators_tenant_user_status",
        "template_collaborators",
        ["tenant_id", "user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_template_collaborators_tenant_user_status", table_name="template_collaborators")
    op.drop_index("ix_template_collaborators_tenant_template_status", table_name="template_collaborators")
    op.drop_index("ix_template_collaborators_user_id", table_name="template_collaborators")
    op.drop_index("ix_template_collaborators_template_id", table_name="template_collaborators")
    op.drop_index("ix_template_collaborators_id", table_name="template_collaborators")
    op.drop_table("template_collaborators")
