"""国内资产引用海外 Connector 凭据。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0033_connector_credential_refs"
down_revision: Union[str, None] = "0032_insight_sync_timestamp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None
def upgrade() -> None:
    bind = op.get_bind()
    for table in ("meta_accounts", "ad_accounts"):
        columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "connector_credential_id" not in columns:
            op.add_column(table, sa.Column("connector_credential_id", sa.String(50), nullable=True))
            op.create_index(f"ix_{table}_connector_credential_id", table, ["connector_credential_id"])
def downgrade() -> None:
    for table in ("ad_accounts", "meta_accounts"):
        op.drop_index(f"ix_{table}_connector_credential_id", table_name=table)
        op.drop_column(table, "connector_credential_id")
