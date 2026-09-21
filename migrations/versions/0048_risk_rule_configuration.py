"""扩展风控规则配置字段，为规则引擎和 dry-run 做准备。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0048_risk_rule_configuration"
down_revision: Union[str, None] = "0047_sinan_user_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """幂等地补充新字段，兼容通过 create_all 创建的历史数据库。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("risk_rules"):
        # 风控表由早期基线/模型初始化创建；若目标库完全没有该表，
        # 让后续部署显式暴露基线问题，而不是在迁移中创建第二套表结构。
        return

    existing = {column["name"] for column in inspector.get_columns("risk_rules")}
    columns = (
        ("scope", sa.Column("scope", sa.JSON(), nullable=True)),
        ("conditions", sa.Column("conditions", sa.JSON(), nullable=True)),
        ("logic", sa.Column("logic", sa.String(8), nullable=False, server_default="AND")),
        ("min_spend", sa.Column("min_spend", sa.BigInteger(), nullable=False, server_default="0")),
        ("min_runtime", sa.Column("min_runtime", sa.Integer(), nullable=False, server_default="0")),
        (
            "cooldown_seconds",
            sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="0"),
        ),
        (
            "max_actions_per_run",
            sa.Column("max_actions_per_run", sa.Integer(), nullable=False, server_default="100"),
        ),
        ("dry_run", sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("whitelist", sa.Column("whitelist", sa.JSON(), nullable=True)),
        ("version", sa.Column("version", sa.Integer(), nullable=False, server_default="1")),
    )

    for name, column in columns:
        if name not in existing:
            op.add_column("risk_rules", column)

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("risk_rules")}
    if "ix_risk_rules_tenant_active_priority" not in indexes:
        op.create_index(
            "ix_risk_rules_tenant_active_priority",
            "risk_rules",
            ["tenant_id", "is_active", "priority"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("risk_rules"):
        return

    indexes = {item["name"] for item in inspector.get_indexes("risk_rules")}
    if "ix_risk_rules_tenant_active_priority" in indexes:
        op.drop_index("ix_risk_rules_tenant_active_priority", table_name="risk_rules")

    existing = {column["name"] for column in sa.inspect(bind).get_columns("risk_rules")}
    for name in (
        "version",
        "whitelist",
        "dry_run",
        "max_actions_per_run",
        "cooldown_seconds",
        "min_runtime",
        "min_spend",
        "logic",
        "conditions",
        "scope",
    ):
        if name in existing:
            op.drop_column("risk_rules", name)
