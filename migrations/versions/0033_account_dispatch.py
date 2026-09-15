from alembic import op
import sqlalchemy as sa
import uuid

revision = "0033_account_dispatch"
down_revision = "0032_insight_sync_timestamp"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("user_accounts", sa.Column("assignment_type", sa.String(20), nullable=False, server_default="MANUAL"))
    op.add_column("user_accounts", sa.Column("assignment_status", sa.String(20), nullable=False, server_default="ACTIVE"))
    op.add_column("user_accounts", sa.Column("assigned_by", sa.String(50)))
    op.add_column("user_accounts", sa.Column("expires_at", sa.DateTime()))
    op.create_table("account_assignment_rules", sa.Column("id", sa.String(50), primary_key=True), sa.Column("tenant_id", sa.String(50), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("priority", sa.String(20), nullable=False, server_default="100"), sa.Column("rule_type", sa.String(32), nullable=False), sa.Column("rule_config", sa.JSON), sa.Column("target_user_id", sa.String(50)), sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime()))
    op.create_table("account_assignment_logs", sa.Column("id", sa.String(50), primary_key=True), sa.Column("tenant_id", sa.String(50), nullable=False), sa.Column("account_id", sa.String(50), nullable=False), sa.Column("from_user_id", sa.String(50)), sa.Column("to_user_id", sa.String(50)), sa.Column("rule_id", sa.String(50)), sa.Column("action", sa.String(32), nullable=False), sa.Column("operator_id", sa.String(50)), sa.Column("reason", sa.String(500)), sa.Column("created_at", sa.DateTime(), nullable=False))

def downgrade():
    op.drop_table("account_assignment_logs"); op.drop_table("account_assignment_rules")
    op.drop_column("user_accounts", "expires_at"); op.drop_column("user_accounts", "assigned_by"); op.drop_column("user_accounts", "assignment_status"); op.drop_column("user_accounts", "assignment_type")
