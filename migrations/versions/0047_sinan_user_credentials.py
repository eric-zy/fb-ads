"""将司南凭据从租户级改为用户级隔离。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0047_sinan_user_credentials"
down_revision: Union[str, None] = "0046_connector_callback_task_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("sinan_credentials")}
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("sinan_credentials")}
    unique_constraints = {
        item.get("name") for item in inspector.get_unique_constraints("sinan_credentials")
    }

    with op.batch_alter_table("sinan_credentials") as batch_op:
        if "user_id" not in columns:
            batch_op.add_column(sa.Column("user_id", sa.String(50), nullable=True))
        if "fk_sinan_credentials_user_id" not in foreign_keys:
            batch_op.create_foreign_key(
                "fk_sinan_credentials_user_id",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if "uq_sinan_credentials_tenant_user" not in unique_constraints:
            batch_op.create_unique_constraint(
                "uq_sinan_credentials_tenant_user",
                ["tenant_id", "user_id"],
            )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("sinan_credentials")}
    if "ix_sinan_credentials_user_id" not in indexes:
        op.create_index(
            "ix_sinan_credentials_user_id",
            "sinan_credentials",
            ["user_id"],
        )

    # 旧版本只有租户级凭据，无法知道真实创建人；尽量归属给该租户最早的管理员。
    # 没有管理员的旧记录保持 NULL，后续由用户重新配置，不会被普通账号读取。
    op.execute(
        sa.text(
            """
            UPDATE sinan_credentials
            SET user_id = (
                SELECT u.id
                FROM users u
                WHERE u.tenant_id = sinan_credentials.tenant_id
                  AND u.role IN ('tenant_admin', 'admin')
                ORDER BY u.created_at ASC, u.id ASC
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("sinan_credentials")}
    foreign_keys = {item.get("name") for item in inspector.get_foreign_keys("sinan_credentials")}
    unique_constraints = {
        item.get("name") for item in inspector.get_unique_constraints("sinan_credentials")
    }

    if "ix_sinan_credentials_user_id" in indexes:
        op.drop_index("ix_sinan_credentials_user_id", table_name="sinan_credentials")

    with op.batch_alter_table("sinan_credentials") as batch_op:
        if "uq_sinan_credentials_tenant_user" in unique_constraints:
            batch_op.drop_constraint("uq_sinan_credentials_tenant_user", type_="unique")
        if "fk_sinan_credentials_user_id" in foreign_keys:
            batch_op.drop_constraint("fk_sinan_credentials_user_id", type_="foreignkey")
        if "user_id" in {column["name"] for column in inspector.get_columns("sinan_credentials")}:
            batch_op.drop_column("user_id")
