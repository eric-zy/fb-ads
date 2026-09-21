"""Add immutable edit-and-republish lineage to campaign jobs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0052_job_revisions"
down_revision: Union[str, None] = "0051_risk_event_notification_channels"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("campaign_jobs")}
    if "parent_job_id" not in columns:
        op.add_column("campaign_jobs", sa.Column("parent_job_id", sa.String(50), nullable=True))
        op.create_foreign_key(
            "fk_campaign_jobs_parent_job_id",
            "campaign_jobs",
            "campaign_jobs",
            ["parent_job_id"],
            ["id"],
        )
        op.create_index("ix_campaign_jobs_parent_job_id", "campaign_jobs", ["parent_job_id"])
    if "revision_no" not in columns:
        op.add_column("campaign_jobs", sa.Column("revision_no", sa.Integer(), nullable=True, server_default="1"))
        op.execute("UPDATE campaign_jobs SET revision_no = 1 WHERE revision_no IS NULL")
        op.alter_column("campaign_jobs", "revision_no", nullable=False, server_default=None)
    if "edit_mode" not in columns:
        op.add_column("campaign_jobs", sa.Column("edit_mode", sa.String(32), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("campaign_jobs")}
    if "edit_mode" in columns:
        op.drop_column("campaign_jobs", "edit_mode")
    if "revision_no" in columns:
        op.drop_column("campaign_jobs", "revision_no")
    if "parent_job_id" in columns:
        op.drop_index("ix_campaign_jobs_parent_job_id", table_name="campaign_jobs")
        op.drop_constraint("fk_campaign_jobs_parent_job_id", "campaign_jobs", type_="foreignkey")
        op.drop_column("campaign_jobs", "parent_job_id")
