"""Record the BM used for each campaign job item."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0028_job_item_access_business"
down_revision: Union[str, None] = "0027_business_asset_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column("campaign_job_items", sa.Column("access_business_id", sa.String(50), nullable=True))
    op.create_foreign_key("fk_job_item_access_business", "campaign_job_items", "meta_accounts", ["access_business_id"], ["id"])
    op.create_index("ix_job_items_access_business", "campaign_job_items", ["access_business_id"])

def downgrade() -> None:
    op.drop_index("ix_job_items_access_business", table_name="campaign_job_items")
    op.drop_constraint("fk_job_item_access_business", "campaign_job_items", type_="foreignkey")
    op.drop_column("campaign_job_items", "access_business_id")
