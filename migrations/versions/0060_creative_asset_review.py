"""Add creative asset review metadata."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0060_creative_asset_review"
down_revision: Union[str, None] = "0059_targeting_packages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("creative_assets")}
    if "review_status" not in columns:
        op.add_column("creative_assets", sa.Column("review_status", sa.String(20), nullable=False, server_default="APPROVED"))
    if "reviewed_by" not in columns:
        op.add_column("creative_assets", sa.Column("reviewed_by", sa.String(50), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column("creative_assets", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    if "review_note" not in columns:
        op.add_column("creative_assets", sa.Column("review_note", sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column("creative_assets", "review_note")
    op.drop_column("creative_assets", "reviewed_at")
    op.drop_column("creative_assets", "reviewed_by")
    op.drop_column("creative_assets", "review_status")
