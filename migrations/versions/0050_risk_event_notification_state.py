"""为风险事件增加通知投递状态，避免重复告警。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0050_risk_event_notification_state"
down_revision: Union[str, None] = "0049_risk_execution_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("risk_events"):
        return

    columns = {item["name"] for item in inspector.get_columns("risk_events")}
    if "notification_status" not in columns:
        op.add_column("risk_events", sa.Column("notification_status", sa.String(20), nullable=False, server_default="PENDING"))
    if "notification_attempts" not in columns:
        op.add_column("risk_events", sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0"))
    if "notification_sent_at" not in columns:
        op.add_column("risk_events", sa.Column("notification_sent_at", sa.DateTime(), nullable=True))
    if "notification_error" not in columns:
        op.add_column("risk_events", sa.Column("notification_error", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("risk_events"):
        return
    columns = {item["name"] for item in inspector.get_columns("risk_events")}
    for name in ("notification_error", "notification_sent_at", "notification_attempts", "notification_status"):
        if name in columns:
            op.drop_column("risk_events", name)
