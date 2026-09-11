"""Add explicit Meta campaign budget sharing flag."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0018_campaign_budget_sharing"
down_revision: Union[str, None] = "0017_meta_business_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "campaign_templates",
        sa.Column("is_adset_budget_sharing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

def downgrade() -> None:
    op.drop_column("campaign_templates", "is_adset_budget_sharing_enabled")
