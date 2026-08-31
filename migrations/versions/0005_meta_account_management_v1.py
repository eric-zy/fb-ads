"""Meta 账号管理 V1 重构（设计文档 §4 / §5 / §6 / §10）

目标：
    Credential → BM → BM 下 Ad Accounts → 同步 / 状态管理 → 可用账户池

本迁移按以下决策实施（与文档的偏离已在 README / 文档注释中说明）：
    1. 保留现有 API 路径 `/api/v1/*`，表名沿用 meta_accounts / credentials
    2. 保留关系方向：credentials.meta_account_id（一 BM 多凭据，支持轮换留痕）
    3. 唯一键改为 (business_id, account_id)：同一 act_xxx 可挂多个 BM
    4. 金额统一 BIGINT 最小货币单位（ad_accounts + insights + campaigns/ads/adgroups + template）

**数据不保留**：账号相关数据清空后重建结构。
    - ad_accounts / meta_accounts / credentials 三张表 TRUNCATE ... CASCADE
    - 级联清空 campaigns / insights / instances / job_items 等所有引用表
    - campaign_templates、users 等与账户无关的数据不受 TRUNCATE CASCADE 影响，予以保留

新增：
    - meta_sync_logs（文档 §10）—— 同步日志，与 audit_logs 职责分离

Revision ID: 0005_meta_account_management_v1
Revises: 0004_meta_account_token_nullable
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_meta_account_management_v1"
down_revision: Union[str, None] = "0004_meta_account_token_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. 清空账号相关数据（级联清理所有引用表）
    # ------------------------------------------------------------------
    op.execute("TRUNCATE TABLE ad_accounts, meta_accounts, credentials CASCADE")

    # ------------------------------------------------------------------
    # 1. meta_accounts（文档 businesses）
    # ------------------------------------------------------------------
    # 移除明文 Token 列：Token 一律由 credentials 表加密存储
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS access_token")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS app_secret")

    op.execute("ALTER TABLE meta_accounts ALTER COLUMN business_id TYPE VARCHAR(64)")

    op.add_column("meta_accounts", sa.Column("timezone", sa.String(64), nullable=True))
    op.add_column("meta_accounts", sa.Column("currency", sa.String(16), nullable=True))
    op.add_column("meta_accounts", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "meta_accounts",
        sa.Column("sync_status", sa.String(32), nullable=False, server_default=sa.text("'PENDING'")),
    )
    op.add_column("meta_accounts", sa.Column("last_synced_at", sa.DateTime(), nullable=True))
    op.add_column("meta_accounts", sa.Column("last_sync_error", sa.Text(), nullable=True))

    # is_active(Boolean) → status(ACTIVE/DISABLED/ARCHIVED)
    op.add_column(
        "meta_accounts",
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'ACTIVE'")),
    )
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS is_active")

    op.create_index("ix_meta_accounts_status", "meta_accounts", ["status"])
    op.create_index("ix_meta_accounts_sync_status", "meta_accounts", ["sync_status"])

    # ------------------------------------------------------------------
    # 2. credentials（文档 meta_credentials）
    # ------------------------------------------------------------------
    op.add_column("credentials", sa.Column("name", sa.String(255), nullable=True))
    op.add_column("credentials", sa.Column("app_id", sa.String(128), nullable=True))

    # ------------------------------------------------------------------
    # 3. ad_accounts（核心表）
    # ------------------------------------------------------------------
    # 旧唯一约束 / 索引：account_id 全局唯一 → 改为 BM 内唯一
    op.execute("ALTER TABLE ad_accounts DROP CONSTRAINT IF EXISTS ad_accounts_account_id_key")
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_status_frozen")

    # meta_account_id → business_id，且 NOT NULL
    op.execute("ALTER TABLE ad_accounts RENAME COLUMN meta_account_id TO business_id")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN account_id TYPE VARCHAR(64)")

    # Meta 侧字段
    op.add_column("ad_accounts", sa.Column("account_status", sa.String(32), nullable=True))
    op.add_column("ad_accounts", sa.Column("effective_status", sa.String(32), nullable=True))
    op.add_column("ad_accounts", sa.Column("disable_reason", sa.String(255), nullable=True))
    # timezone 原表已存在，只需放宽长度（原 VARCHAR(50) → VARCHAR(64)）
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN timezone TYPE VARCHAR(64)")

    # 金额字段：FLOAT → BIGINT（最小货币单位）
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS total_spend")
    op.add_column(
        "ad_accounts", sa.Column("amount_spent", sa.BigInteger(), nullable=True, server_default=sa.text("0"))
    )
    op.add_column(
        "ad_accounts", sa.Column("spend_cap", sa.BigInteger(), nullable=True, server_default=sa.text("0"))
    )
    op.add_column(
        "ad_accounts", sa.Column("balance", sa.BigInteger(), nullable=True, server_default=sa.text("0"))
    )
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN daily_spend_limit TYPE BIGINT USING 0")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN monthly_spend_limit TYPE BIGINT USING 0")

    # 系统侧状态：取代 status + is_frozen 双写
    op.add_column(
        "ad_accounts",
        sa.Column("system_status", sa.String(32), nullable=False, server_default=sa.text("'ACTIVE'")),
    )
    op.add_column("ad_accounts", sa.Column("system_status_reason", sa.String(500), nullable=True))
    op.add_column("ad_accounts", sa.Column("system_status_at", sa.DateTime(), nullable=True))
    op.add_column("ad_accounts", sa.Column("capabilities", sa.JSON(), nullable=True))
    op.add_column("ad_accounts", sa.Column("last_synced_at", sa.DateTime(), nullable=True))
    op.add_column("ad_accounts", sa.Column("last_sync_error", sa.Text(), nullable=True))

    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS is_frozen")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS frozen_reason")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS frozen_at")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS unfreeze_at")

    op.create_unique_constraint("uq_business_account", "ad_accounts", ["business_id", "account_id"])
    # 历史遗留：ad_accounts → meta_accounts 的外键此前从未创建（同库其它表都有），
    # 重构时一并补上，保证 BM 删除 / 引用完整性有数据库层兜底
    op.create_foreign_key(
        "fk_ad_accounts_business", "ad_accounts", "meta_accounts",
        ["business_id"], ["id"],
    )
    op.create_index("ix_ad_accounts_system_status", "ad_accounts", ["system_status"])
    op.create_index("ix_ad_accounts_account_status", "ad_accounts", ["account_status"])
    op.create_index("ix_ad_accounts_effective_status", "ad_accounts", ["effective_status"])

    # ------------------------------------------------------------------
    # 4. 金额改造：insights / campaigns / ad_groups / ads / campaign_templates
    # ------------------------------------------------------------------
    for table in ("account_insights", "campaign_insights", "ad_insights"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN spend TYPE BIGINT USING 0")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN spend SET DEFAULT 0")

    op.execute("ALTER TABLE campaigns ALTER COLUMN spend TYPE BIGINT USING 0")
    op.execute("ALTER TABLE campaigns ALTER COLUMN spend SET DEFAULT 0")
    op.execute("ALTER TABLE campaigns ALTER COLUMN budget TYPE BIGINT USING NULL")
    op.execute("ALTER TABLE campaigns ALTER COLUMN daily_budget TYPE BIGINT USING NULL")

    op.execute("ALTER TABLE ad_groups ALTER COLUMN spend TYPE BIGINT USING 0")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN spend SET DEFAULT 0")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN daily_budget TYPE BIGINT USING NULL")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN bid_amount TYPE BIGINT USING NULL")

    op.execute("ALTER TABLE ads ALTER COLUMN spend TYPE BIGINT USING 0")
    op.execute("ALTER TABLE ads ALTER COLUMN spend SET DEFAULT 0")

    op.execute("ALTER TABLE campaign_templates ALTER COLUMN daily_budget TYPE BIGINT USING NULL")
    op.execute("ALTER TABLE campaign_templates ALTER COLUMN lifetime_budget TYPE BIGINT USING NULL")
    op.execute("ALTER TABLE publish_tasks ALTER COLUMN daily_budget TYPE BIGINT USING NULL")

    # ------------------------------------------------------------------
    # 5. meta_sync_logs（文档 §10）
    # ------------------------------------------------------------------
    op.create_table(
        "meta_sync_logs",
        sa.Column("id", sa.String(50), nullable=False),
        sa.Column("business_id", sa.String(50), nullable=True),
        sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["meta_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meta_sync_logs_business_id"), "meta_sync_logs", ["business_id"])
    op.create_index(op.f("ix_meta_sync_logs_created_at"), "meta_sync_logs", ["created_at"])
    op.create_index(op.f("ix_meta_sync_logs_status"), "meta_sync_logs", ["status"])
    op.create_index(op.f("ix_meta_sync_logs_celery_task_id"), "meta_sync_logs", ["celery_task_id"])
    op.create_index(op.f("ix_meta_sync_logs_id"), "meta_sync_logs", ["id"])


def downgrade() -> None:
    """回滚结构（同样不保留数据）"""
    op.drop_table("meta_sync_logs")

    op.execute("TRUNCATE TABLE ad_accounts, meta_accounts, credentials CASCADE")

    # 金额回滚为 FLOAT
    op.execute("ALTER TABLE campaign_templates ALTER COLUMN lifetime_budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE campaign_templates ALTER COLUMN daily_budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE publish_tasks ALTER COLUMN daily_budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE ads ALTER COLUMN spend TYPE DOUBLE PRECISION USING 0")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN bid_amount TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN daily_budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE ad_groups ALTER COLUMN spend TYPE DOUBLE PRECISION USING 0")
    op.execute("ALTER TABLE campaigns ALTER COLUMN daily_budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE campaigns ALTER COLUMN budget TYPE DOUBLE PRECISION USING NULL")
    op.execute("ALTER TABLE campaigns ALTER COLUMN spend TYPE DOUBLE PRECISION USING 0")
    for table in ("account_insights", "campaign_insights", "ad_insights"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN spend TYPE DOUBLE PRECISION USING 0")

    # ad_accounts 回滚
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_effective_status")
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_account_status")
    op.execute("DROP INDEX IF EXISTS ix_ad_accounts_system_status")
    op.execute("ALTER TABLE ad_accounts DROP CONSTRAINT IF EXISTS uq_business_account")
    op.execute("ALTER TABLE ad_accounts DROP CONSTRAINT IF EXISTS fk_ad_accounts_business")

    op.add_column("ad_accounts", sa.Column("status", sa.String(32), nullable=True))
    op.add_column("ad_accounts", sa.Column("is_frozen", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("ad_accounts", sa.Column("frozen_reason", sa.String(500), nullable=True))
    op.add_column("ad_accounts", sa.Column("frozen_at", sa.DateTime(), nullable=True))
    op.add_column("ad_accounts", sa.Column("unfreeze_at", sa.DateTime(), nullable=True))
    op.add_column("ad_accounts", sa.Column("total_spend", sa.Float(), nullable=True, server_default=sa.text("0")))

    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS last_sync_error")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS last_synced_at")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS capabilities")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS system_status_at")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS system_status_reason")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS system_status")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS balance")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS spend_cap")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS amount_spent")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS disable_reason")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN timezone TYPE VARCHAR(50)")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS effective_status")
    op.execute("ALTER TABLE ad_accounts DROP COLUMN IF EXISTS account_status")

    op.execute("ALTER TABLE ad_accounts ALTER COLUMN daily_spend_limit TYPE DOUBLE PRECISION USING 0")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN monthly_spend_limit TYPE DOUBLE PRECISION USING 0")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN account_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE ad_accounts RENAME COLUMN business_id TO meta_account_id")
    op.execute("ALTER TABLE ad_accounts ALTER COLUMN meta_account_id DROP NOT NULL")

    # credentials 回滚
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS app_id")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS name")

    # meta_accounts 回滚
    op.execute("DROP INDEX IF EXISTS ix_meta_accounts_sync_status")
    op.execute("DROP INDEX IF EXISTS ix_meta_accounts_status")
    op.add_column("meta_accounts", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.text("true")))
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS last_sync_error")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS last_synced_at")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS sync_status")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS currency")
    op.execute("ALTER TABLE meta_accounts DROP COLUMN IF EXISTS timezone")
    op.execute("ALTER TABLE meta_accounts ALTER COLUMN business_id TYPE VARCHAR(50)")
    op.add_column("meta_accounts", sa.Column("app_secret", sa.String(100), nullable=True))
    op.add_column("meta_accounts", sa.Column("access_token", sa.String(512), nullable=True))
