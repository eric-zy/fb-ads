"""Add non-sensitive account billing status fields."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0019_account_payment_status"
down_revision: Union[str, None] = "0018_campaign_budget_sharing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ad_accounts")}
    definitions = {
        "payment_status": sa.Column("payment_status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        "payment_source": sa.Column("payment_source", sa.String(32), nullable=True),
        "payment_error_code": sa.Column("payment_error_code", sa.String(64), nullable=True),
        "payment_error_message": sa.Column("payment_error_message", sa.String(500), nullable=True),
        "payment_checked_at": sa.Column("payment_checked_at", sa.DateTime(), nullable=True),
    }
    for name, column in definitions.items():
        if name not in columns:
            op.add_column("ad_accounts", column)

def downgrade() -> None:
    for name in ("payment_checked_at", "payment_error_message", "payment_error_code", "payment_source", "payment_status"):
        op.drop_column("ad_accounts", name)
