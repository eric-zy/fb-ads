"""修复历史数据库中缺失的 Meta 默认凭据及凭据溯源字段。"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_repair_credential_columns"
down_revision: Union[str, None] = "0012_repair_tenant_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("meta_accounts") and inspector.has_table("credentials"):
        if "default_credential_id" not in _columns(inspector, "meta_accounts"):
            op.add_column(
                "meta_accounts",
                sa.Column("default_credential_id", sa.String(50), nullable=True),
            )
        indexes = {item["name"] for item in inspector.get_indexes("meta_accounts")}
        if "ix_meta_accounts_default_credential" not in indexes:
            op.create_index(
                "ix_meta_accounts_default_credential",
                "meta_accounts",
                ["default_credential_id"],
            )
        foreign_keys = inspector.get_foreign_keys("meta_accounts")
        if not any(item.get("name") == "fk_meta_accounts_default_credential" for item in foreign_keys):
            op.create_foreign_key(
                "fk_meta_accounts_default_credential",
                "meta_accounts",
                "credentials",
                ["default_credential_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if inspector.has_table("credentials"):
        existing = _columns(inspector, "credentials")
        additions = {
            "source": sa.Column("source", sa.String(32), nullable=True, server_default="MANUAL"),
            "scopes": sa.Column("scopes", sa.JSON(), nullable=True),
            "granted_by_user_id": sa.Column("granted_by_user_id", sa.String(50), nullable=True),
            "meta_user_id": sa.Column("meta_user_id", sa.String(64), nullable=True),
        }
        for name, column in additions.items():
            if name not in existing:
                op.add_column("credentials", column)

        foreign_keys = sa.inspect(bind).get_foreign_keys("credentials")
        if not any(item.get("name") == "fk_credentials_granted_by_user" for item in foreign_keys):
            op.create_foreign_key(
                "fk_credentials_granted_by_user",
                "credentials",
                "users",
                ["granted_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    pass
