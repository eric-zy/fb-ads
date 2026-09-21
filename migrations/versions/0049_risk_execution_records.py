"""新增风控执行记录，并补充风险事件处理人字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0049_risk_execution_records"
down_revision: Union[str, None] = "0048_risk_rule_configuration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("risk_events"):
        event_columns = {item["name"] for item in inspector.get_columns("risk_events")}
        if "resolved_by" not in event_columns:
            op.add_column("risk_events", sa.Column("resolved_by", sa.String(50), nullable=True))

    if not inspector.has_table("risk_executions"):
        op.create_table(
            "risk_executions",
            sa.Column("id", sa.String(50), nullable=False),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("rule_id", sa.String(50), nullable=False),
            sa.Column("ad_account_id", sa.String(50), nullable=False),
            sa.Column("target_type", sa.String(20), nullable=False),
            sa.Column("target_id", sa.String(128), nullable=False),
            sa.Column("rule_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("mode", sa.String(20), nullable=False, server_default="LIVE"),
            sa.Column("status", sa.String(20), nullable=False, server_default="MATCHED"),
            sa.Column("action", sa.String(32), nullable=False, server_default="ALERT"),
            sa.Column("matched_conditions", sa.JSON(), nullable=True),
            sa.Column("metrics_snapshot", sa.JSON(), nullable=True),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("provider_response", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["rule_id"], ["risk_rules.id"]),
            sa.ForeignKeyConstraint(["ad_account_id"], ["ad_accounts.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uq_risk_executions_tenant_idempotency",
            ),
        )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("risk_executions")}
    for name, columns in (
        ("ix_risk_executions_id", ["id"]),
        ("ix_risk_executions_run_id", ["run_id"]),
        ("ix_risk_executions_rule_id", ["rule_id"]),
        ("ix_risk_executions_tenant_created", ["tenant_id", "created_at"]),
        ("ix_risk_executions_tenant_account", ["tenant_id", "ad_account_id"]),
        ("ix_risk_executions_tenant_status", ["tenant_id", "status"]),
        ("ix_risk_executions_tenant_rule", ["tenant_id", "rule_id"]),
    ):
        if name not in indexes:
            op.create_index(name, "risk_executions", columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("risk_executions"):
        op.drop_table("risk_executions")
    if inspector.has_table("risk_events"):
        columns = {item["name"] for item in sa.inspect(bind).get_columns("risk_events")}
        if "resolved_by" in columns:
            op.drop_column("risk_events", "resolved_by")
