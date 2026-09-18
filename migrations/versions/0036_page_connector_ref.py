"""Page 仅保存海外 Connector 凭据引用，允许不保存 Page Token。"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0036_page_connector_ref"
down_revision: Union[str, None] = "0035_connector_credential_refs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None

def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("meta_pages")}
    if "connector_credential_id" not in columns:
        op.add_column("meta_pages", sa.Column("connector_credential_id", sa.String(50), nullable=True))
        op.create_index("ix_meta_pages_connector_credential_id", "meta_pages", ["connector_credential_id"])
    op.alter_column("meta_pages", "page_access_token_encrypted", existing_type=sa.Text(), nullable=True)

def downgrade() -> None:
    op.alter_column("meta_pages", "page_access_token_encrypted", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_meta_pages_connector_credential_id", table_name="meta_pages")
    op.drop_column("meta_pages", "connector_credential_id")
