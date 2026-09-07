"""修复历史 create_all 数据库中未补齐的 tenant_id 字段。"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_repair_tenant_columns"
down_revision: Union[str, None] = "0011_insight_business_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_TENANT_ID = "tenant_default"

STRICT_TABLES = [
    "user_accounts", "meta_accounts", "ad_accounts", "creative_assets",
    "campaigns", "ad_groups", "ads", "publish_tasks", "published_ads",
    "account_insights", "campaign_insights", "ad_insights", "risk_events",
    "campaign_templates", "campaign_instances", "adset_instances",
    "ad_instances", "credentials", "campaign_jobs", "campaign_job_items",
    "meta_sync_logs",
]
NULLABLE_TABLES = ["users", "audit_logs", "risk_rules"]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tenants"):
        return

    bind.execute(sa.text(
        "INSERT INTO tenants (id, name, slug, status, plan, created_at, updated_at, is_trial) "
        "VALUES (:id, :name, :slug, 'ACTIVE', 'FREE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, false) "
        "ON CONFLICT (id) DO NOTHING"
    ), {"id": DEFAULT_TENANT_ID, "name": "默认租户", "slug": "default"})

    for table in STRICT_TABLES + NULLABLE_TABLES:
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "tenant_id" not in columns:
            op.add_column(table, sa.Column("tenant_id", sa.String(50), nullable=True))
        bind.execute(sa.text(f"UPDATE {table} SET tenant_id = :tenant WHERE tenant_id IS NULL"), {"tenant": DEFAULT_TENANT_ID})
        if table in STRICT_TABLES:
            op.alter_column(table, "tenant_id", existing_type=sa.String(50), nullable=False)
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"))

        foreign_keys = inspector.get_foreign_keys(table)
        if not any(fk.get("name") == f"fk_{table}_tenant" for fk in foreign_keys):
            op.create_foreign_key(f"fk_{table}_tenant", table, "tenants", ["tenant_id"], ["id"])


def downgrade() -> None:
    # 保留租户字段，避免回滚破坏线上数据隔离结构。
    pass
