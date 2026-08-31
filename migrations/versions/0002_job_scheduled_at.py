"""为 campaign_jobs 增加定时执行支持

- scheduled_at：计划执行时间（为空表示立即执行）
- celery_task_id：Celery 编排任务 ID，取消定时任务时用于 revoke

用于支撑「定时投放」场景：创建 Job 时指定未来时间，
由 Celery 的 eta 机制延迟派发，Job 在此期间保持 QUEUED 状态。

Revision ID: 0002_job_scheduled_at
Revises: 0001_campaign_template
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_job_scheduled_at"
down_revision: Union[str, None] = "0001_campaign_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_jobs",
        sa.Column("scheduled_at", sa.DateTime(), nullable=True,
                  comment="计划执行时间（UTC），为空表示立即执行"),
    )
    op.add_column(
        "campaign_jobs",
        sa.Column("celery_task_id", sa.String(64), nullable=True,
                  comment="Celery 编排任务 ID，用于撤销定时任务"),
    )
    op.create_index("ix_campaign_jobs_scheduled_at", "campaign_jobs", ["scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_campaign_jobs_scheduled_at", table_name="campaign_jobs")
    op.drop_column("campaign_jobs", "celery_task_id")
    op.drop_column("campaign_jobs", "scheduled_at")
