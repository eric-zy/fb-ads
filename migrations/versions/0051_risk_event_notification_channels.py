"""保存风险事件的逐渠道通知结果，支持只重试失败渠道。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0051_risk_event_notification_channels"
down_revision: Union[str, None] = "0050_risk_event_notification_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("risk_events"):
        columns = {item["name"] for item in inspector.get_columns("risk_events")}
        if "notification_results" not in columns:
            op.add_column("risk_events", sa.Column("notification_results", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("risk_events"):
        columns = {item["name"] for item in inspector.get_columns("risk_events")}
        if "notification_results" in columns:
            op.drop_column("risk_events", "notification_results")
