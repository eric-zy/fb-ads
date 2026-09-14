"""Mark direct-publish internal configurations so they stay out of template lists."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029_template_temporary"
down_revision: Union[str, None] = "0028_job_item_access_business"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_templates",
        sa.Column("is_temporary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_campaign_templates_tenant_temporary",
        "campaign_templates",
        ["tenant_id", "is_temporary"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_templates_tenant_temporary", table_name="campaign_templates")
    op.drop_column("campaign_templates", "is_temporary")
