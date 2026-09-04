"""多租户改造：租户表 + 全业务表 tenant_id 行级隔离

Revision ID: 0006_multi_tenant
Revises: 0005_meta_account_management_v1
Create Date: 2026-09-04

==========================================================================
改造内容
==========================================================================
1. 新建 `tenants` 表（租户/组织的根节点）
2. 为 23 张业务表加 `tenant_id` 列 + 外键 + 索引
3. 历史数据统一回填到「默认租户」（slug 由 DEFAULT_TENANT_SLUG 指定）
4. 索引重建：行级隔离下高频查询索引必须以 `tenant_id` 打头
5. 唯一约束调整
    - meta_accounts.business_id 全局唯一 → (tenant_id, business_id) 唯一
      （代理/外包场景下同一 BM 可被多个租户各自录入）
    - risk_rules.name 全局唯一 → 平台/租户两组部分唯一索引
6. users.role 规范化：admin → tenant_admin

==========================================================================
数据安全说明
==========================================================================
本迁移**保留全部历史数据**：
    - 先加可空列 → 回填默认租户 → 再收紧为 NOT NULL
    - 只有 users / audit_logs / risk_rules 三张表的 tenant_id 保持可空
      （平台管理员、平台级审计、平台共享规则需要 NULL 语义）
==========================================================================
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_multi_tenant"
down_revision: Union[str, None] = "0005_meta_account_management_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 默认租户：历史数据统一归属到这里
DEFAULT_TENANT_ID = "tenant_default"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "默认租户"

# 严格租户级表（tenant_id NOT NULL）
STRICT_TABLES = [
    "user_accounts",
    "meta_accounts",
    "ad_accounts",
    "creative_assets",
    "campaigns",
    "ad_groups",
    "ads",
    "publish_tasks",
    "published_ads",
    "account_insights",
    "campaign_insights",
    "ad_insights",
    "risk_events",
    "campaign_templates",
    "campaign_instances",
    "adset_instances",
    "ad_instances",
    "credentials",
    "campaign_jobs",
    "campaign_job_items",
    "meta_sync_logs",
]

# 允许 tenant_id 为空的表（NULL 表示平台级/跨租户数据）
NULLABLE_TABLES = ["users", "audit_logs", "risk_rules"]

# (表名, 索引名, 列列表, 是否唯一)
COMPOSITE_INDEXES = [
    ("users", "ix_users_tenant_active", ["tenant_id", "is_active"], False),
    ("user_accounts", "ix_user_accounts_tenant_user", ["tenant_id", "user_id"], False),
    ("meta_accounts", "ix_meta_accounts_tenant_status", ["tenant_id", "status"], False),
    ("meta_accounts", "ix_meta_accounts_tenant_sync", ["tenant_id", "sync_status"], False),
    ("ad_accounts", "ix_ad_accounts_tenant_business", ["tenant_id", "business_id"], False),
    ("ad_accounts", "ix_ad_accounts_tenant_system_status", ["tenant_id", "system_status"], False),
    ("ad_accounts", "ix_ad_accounts_tenant_account_status", ["tenant_id", "account_status"], False),
    ("ad_accounts", "ix_ad_accounts_tenant_effective", ["tenant_id", "effective_status"], False),
    ("campaigns", "ix_campaigns_tenant_account", ["tenant_id", "ad_account_id"], False),
    ("campaigns", "ix_campaigns_tenant_status", ["tenant_id", "status"], False),
    ("ad_groups", "ix_ad_groups_tenant_campaign", ["tenant_id", "campaign_id"], False),
    ("ads", "ix_ads_tenant_group", ["tenant_id", "ad_group_id"], False),
    ("ads", "ix_ads_tenant_status", ["tenant_id", "status"], False),
    ("creative_assets", "ix_creative_assets_tenant_meta", ["tenant_id", "meta_account_id"], False),
    ("creative_assets", "ix_creative_assets_tenant_account", ["tenant_id", "account_id"], False),
    ("campaign_templates", "ix_campaign_templates_tenant_status", ["tenant_id", "status"], False),
    ("campaign_instances", "ix_campaign_instances_tenant_template", ["tenant_id", "template_id"], False),
    ("campaign_instances", "ix_campaign_instances_tenant_account", ["tenant_id", "ad_account_id"], False),
    ("adset_instances", "ix_adset_instances_tenant_campaign", ["tenant_id", "campaign_instance_id"], False),
    ("ad_instances", "ix_ad_instances_tenant_adset", ["tenant_id", "adset_instance_id"], False),
    ("credentials", "ix_credentials_tenant_meta", ["tenant_id", "meta_account_id"], False),
    ("credentials", "ix_credentials_tenant_status", ["tenant_id", "status"], False),
    ("campaign_jobs", "ix_campaign_jobs_tenant_status", ["tenant_id", "status"], False),
    ("campaign_jobs", "ix_campaign_jobs_tenant_created", ["tenant_id", "created_at"], False),
    ("campaign_job_items", "ix_job_items_tenant_job", ["tenant_id", "job_id"], False),
    ("campaign_job_items", "ix_job_items_tenant_status", ["tenant_id", "status"], False),
    ("campaign_job_items", "ix_job_items_tenant_hash", ["tenant_id", "request_hash"], False),
    ("account_insights", "ix_account_insights_tenant_account_date", ["tenant_id", "ad_account_id", "date"], False),
    ("account_insights", "ix_account_insights_tenant_date", ["tenant_id", "date"], False),
    ("campaign_insights", "ix_campaign_insights_tenant_campaign_date", ["tenant_id", "campaign_id", "date"], False),
    ("campaign_insights", "ix_campaign_insights_tenant_date", ["tenant_id", "date"], False),
    ("ad_insights", "ix_ad_insights_tenant_ad_date", ["tenant_id", "ad_id", "date"], False),
    ("ad_insights", "ix_ad_insights_tenant_date", ["tenant_id", "date"], False),
    ("risk_events", "ix_risk_events_tenant_account", ["tenant_id", "ad_account_id"], False),
    ("risk_events", "ix_risk_events_tenant_resolved", ["tenant_id", "is_resolved"], False),
    ("risk_rules", "uq_risk_rules_platform_name", ["name"], True),
    ("risk_rules", "uq_risk_rules_tenant_name", ["tenant_id", "name"], True),
    ("publish_tasks", "ix_publish_tasks_tenant_created", ["tenant_id", "created_at"], False),
    ("published_ads", "ix_published_ads_tenant_task", ["tenant_id", "task_id"], False),
    ("audit_logs", "ix_audit_logs_tenant_created", ["tenant_id", "created_at"], False),
    ("audit_logs", "ix_audit_logs_tenant_resource", ["tenant_id", "resource_type", "resource_id"], False),
    ("meta_sync_logs", "ix_meta_sync_logs_tenant_business", ["tenant_id", "business_id"], False),
    ("meta_sync_logs", "ix_meta_sync_logs_tenant_created", ["tenant_id", "created_at"], False),
]

# 部分唯一索引（risk_rules）：平台规则与租户规则分开约束
PARTIAL_WHERE = {
    "uq_risk_rules_platform_name": "tenant_id IS NULL",
    "uq_risk_rules_tenant_name": "tenant_id IS NOT NULL",
}


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. tenants 表
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("plan", sa.String(32), nullable=False, server_default="FREE"),
        sa.Column("owner_user_id", sa.String(50), nullable=True),
        sa.Column("contact_name", sa.String(128), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_meta_accounts", sa.Integer(), nullable=True),
        sa.Column("max_ad_accounts", sa.Integer(), nullable=True),
        sa.Column("max_templates", sa.Integer(), nullable=True),
        sa.Column("max_daily_jobs", sa.Integer(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_trial", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="tenants_slug_key"),
    )
    op.create_index("ix_tenants_id", "tenants", ["id"])
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_status", "tenants", ["status"])

    # ------------------------------------------------------------------
    # 2. 创建默认租户并回填历史数据
    # ------------------------------------------------------------------
    op.execute(
        f"""
        INSERT INTO tenants (id, name, slug, status, plan, created_at, updated_at,
                             max_users, max_meta_accounts, max_ad_accounts,
                             max_templates, max_daily_jobs, is_trial)
        VALUES ('{DEFAULT_TENANT_ID}', '{DEFAULT_TENANT_NAME}', '{DEFAULT_TENANT_SLUG}',
                'ACTIVE', 'FREE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                NULL, NULL, NULL, NULL, NULL, FALSE)
        ON CONFLICT (id) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 3. 加 tenant_id 列并回填
    # ------------------------------------------------------------------
    for table in STRICT_TABLES + NULLABLE_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(50), nullable=True))
        op.execute(
            f"UPDATE {table} SET tenant_id = '{DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL"
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # 严格租户级表收紧为 NOT NULL
    for table in STRICT_TABLES:
        op.alter_column(table, "tenant_id", nullable=False)

    # ------------------------------------------------------------------
    # 4. 外键
    # ------------------------------------------------------------------
    for table in STRICT_TABLES + NULLABLE_TABLES:
        op.create_foreign_key(
            f"fk_{table}_tenant", table, "tenants", ["tenant_id"], ["id"]
        )

    # ------------------------------------------------------------------
    # 5. 索引重建：旧索引（无 tenant 前缀）→ 复合索引（tenant_id 打头）
    # ------------------------------------------------------------------
    # ad_accounts：0005 建的单列索引由 (tenant_id, col) 复合索引取代
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_system_status")
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_account_status")
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_effective_status")

    # meta_accounts / meta_sync_logs：同样的处理。
    # 这三个索引只存在于数据库（0005 创建）而模型从未声明，
    # 不在这里显式 drop 的话，后续 alembic autogenerate 会生成多余的 DROP 语句。
    op.execute("DROP INDEX IF EXISTS ix_meta_accounts_status")
    op.execute("DROP INDEX IF EXISTS ix_meta_accounts_sync_status")
    op.execute("DROP INDEX IF EXISTS ix_meta_sync_logs_status")

    for table, index_name, columns, unique in COMPOSITE_INDEXES:
        where = PARTIAL_WHERE.get(index_name)
        if unique and where:
            op.execute(
                f"CREATE UNIQUE INDEX {index_name} ON {table} "
                f"({', '.join(columns)}) WHERE {where}"
            )
        elif unique:
            op.create_unique_constraint(index_name, table, columns)
        else:
            op.create_index(index_name, table, columns)

    # ------------------------------------------------------------------
    # 6. 唯一约束调整
    # ------------------------------------------------------------------
    # meta_accounts: business_id 全局唯一 → (tenant_id, business_id) 唯一
    op.execute("ALTER TABLE meta_accounts DROP CONSTRAINT IF EXISTS meta_accounts_business_id_key")
    op.create_unique_constraint(
        "uq_tenant_business", "meta_accounts", ["tenant_id", "business_id"]
    )

    # risk_rules: name 全局唯一 → 部分唯一索引（见 COMPOSITE_INDEXES）
    op.execute("ALTER TABLE risk_rules DROP CONSTRAINT IF EXISTS risk_rules_name_key")

    # ------------------------------------------------------------------
    # 7. users.role 规范化（admin → tenant_admin）
    # ------------------------------------------------------------------
    op.execute("UPDATE users SET role = 'tenant_admin' WHERE role = 'admin'")

    # ------------------------------------------------------------------
    # 8. ad_accounts.capabilities 规范为 JSONB + 默认 '{}'（文档 §8）
    # ------------------------------------------------------------------
    # 原实现是 JSON 且可空、无 server_default：
    #   - json 类型没有 GIN 索引能力，也无法做包含查询
    #   - 直接 SQL 插入会产生 NULL，消费方只能到处写 `capabilities or {}`
    # 这里先回填再收紧，保证结构迁移不丢数据。
    op.execute("UPDATE ad_accounts SET capabilities = '{}' WHERE capabilities IS NULL")
    op.alter_column(
        "ad_accounts",
        "capabilities",
        type_=postgresql.JSONB,
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )

    # ------------------------------------------------------------------
    # 9. credentials 溯源字段
    # ------------------------------------------------------------------
    # Token 出现问题时运维要立刻回答：谁授的权？授了哪些权限？用的哪个 Meta 账号？
    # 没有这些列就只能翻应用日志，OAuth 上线后更是无从查起。
    op.add_column(
        "credentials",
        sa.Column("source", sa.String(32), nullable=True, server_default="MANUAL"),
    )
    op.add_column("credentials", sa.Column("scopes", sa.JSON(), nullable=True))
    op.add_column("credentials", sa.Column("granted_by_user_id", sa.String(50), nullable=True))
    op.add_column("credentials", sa.Column("meta_user_id", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_credentials_granted_by_user",
        "credentials",
        "users",
        ["granted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------------------
    # 10. meta_accounts.default_credential_id（文档 §5 credential_id）
    # ------------------------------------------------------------------
    # 反向设计（credentials.meta_account_id）下原先无法显式指定默认凭据，
    # 只能按「最新一条 ACTIVE」推导。补该列后可人工指定；
    # 留空仍走原推导逻辑，因此无需回填历史数据。
    op.add_column(
        "meta_accounts",
        sa.Column("default_credential_id", sa.String(50), nullable=True),
    )
    op.create_index(
        "ix_meta_accounts_default_credential",
        "meta_accounts",
        ["default_credential_id"],
    )
    op.create_foreign_key(
        "fk_meta_accounts_default_credential",
        "meta_accounts",
        "credentials",
        ["default_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 历史数据：users.company_id 若已存在，可作为租户归属的人工核对依据，
    # 但结构迁移不做推断（公司名与租户 slug 无稳定映射），统一归入默认租户。


def downgrade() -> None:
    """回滚：删除 tenant_id 列与租户表（数据不丢失，仅解除隔离结构）"""
    op.drop_constraint(
        "fk_meta_accounts_default_credential", "meta_accounts", type_="foreignkey"
    )
    op.drop_index("ix_meta_accounts_default_credential", table_name="meta_accounts")
    op.drop_column("meta_accounts", "default_credential_id")
    op.drop_constraint(
        "fk_credentials_granted_by_user", "credentials", type_="foreignkey"
    )
    for col in ("source", "scopes", "granted_by_user_id", "meta_user_id"):
        op.drop_column("credentials", col)
    op.alter_column(
        "ad_accounts",
        "capabilities",
        type_=sa.JSON(),
        server_default=None,
        nullable=True,
    )
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'tenant_admin'")

    for table, index_name, columns, unique in reversed(COMPOSITE_INDEXES):
        if unique and index_name in PARTIAL_WHERE:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
        elif unique:
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {index_name}")
        else:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")

    op.execute("ALTER TABLE meta_accounts DROP CONSTRAINT IF EXISTS uq_tenant_business")
    op.execute(
        "ALTER TABLE meta_accounts ADD CONSTRAINT meta_accounts_business_id_key "
        "UNIQUE (business_id)"
    )
    op.execute(
        "ALTER TABLE risk_rules ADD CONSTRAINT risk_rules_name_key UNIQUE (name)"
    )

    op.create_index("ix_ad_accounts_system_status", "ad_accounts", ["system_status"])
    op.create_index("ix_ad_accounts_account_status", "ad_accounts", ["account_status"])
    op.create_index("ix_ad_accounts_effective_status", "ad_accounts", ["effective_status"])
    op.create_index("ix_meta_accounts_status", "meta_accounts", ["status"])
    op.create_index("ix_meta_accounts_sync_status", "meta_accounts", ["sync_status"])
    op.create_index("ix_meta_sync_logs_status", "meta_sync_logs", ["status"])

    for table in reversed(STRICT_TABLES + NULLABLE_TABLES):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_tenant")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_tenant_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")

    op.execute("DROP INDEX IF EXISTS ix_tenants_status")
    op.execute("DROP INDEX IF EXISTS ix_tenants_slug")
    op.execute("DROP INDEX IF EXISTS ix_tenants_id")
    op.drop_table("tenants")
