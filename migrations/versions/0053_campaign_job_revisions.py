"""Persist edit-and-republish drafts and validation snapshots."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0053_campaign_job_revisions"
down_revision: Union[str, None] = "0052_job_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("campaign_job_revisions"):
        return
    op.create_table(
        "campaign_job_revisions",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("base_job_id", sa.String(50), nullable=False),
        sa.Column("published_job_id", sa.String(50), nullable=True),
        sa.Column("template_id", sa.String(50), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("account_ids", sa.JSON(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("validation_result", sa.JSON(), nullable=True),
        sa.Column("edit_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["base_job_id"], ["campaign_jobs.id"]),
        sa.ForeignKeyConstraint(["published_job_id"], ["campaign_jobs.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["campaign_templates.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("base_job_id", "version", name="uq_job_revision_version"),
    )
    op.create_index("ix_campaign_job_revisions_id", "campaign_job_revisions", ["id"])
    op.create_index("ix_campaign_job_revisions_base_job_id", "campaign_job_revisions", ["base_job_id"])
    op.create_index("ix_campaign_job_revisions_published_job_id", "campaign_job_revisions", ["published_job_id"])
    op.create_index("ix_campaign_job_revisions_template_id", "campaign_job_revisions", ["template_id"])
    op.create_index("ix_job_revisions_tenant_status", "campaign_job_revisions", ["tenant_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("campaign_job_revisions"):
        op.drop_table("campaign_job_revisions")
