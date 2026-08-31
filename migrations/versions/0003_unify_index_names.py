"""统一索引命名：旧索引名在 schema 内全局冲突

背景：
    早期模型里多张表复用了相同的显式索引名（ix_ad_account_id / ix_status /
    ix_ad_group_id / ix_campaign_id ...），而 PostgreSQL 的索引名在 schema 内
    全局唯一。后果有两层：

    1. `Base.metadata.create_all()` 直接失败：
       `index ix_ad_account_id already exists`（测试库建表即崩）。
    2. 只有"先建成功"的那张表拿到索引，其余表（risk_events / ads / ad_groups 等）
       永久缺失对应索引，查询全表扫描。

    另外，部分列同时写了 `index=True` 和等价的显式 Index，等于同一列建了两遍索引。

    模型侧已统一为 `ix_<表名>_<列>` 命名、去掉与显式 Index 重复的 `index=True`。
    本迁移把存量库对齐到新命名：
      - 新名已存在（历史隐式索引）→ 删除冗余的旧名索引
      - 新名不存在 → 把旧名索引 RENAME 过去，避免重建（无需扫表）
      - 两端都不存在 → 补建索引

    全部操作按运行时实际状态判断，可重复执行。

Revision ID: 0003_unify_index_names
Revises: 0002_job_scheduled_at
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_unify_index_names"
down_revision: Union[str, None] = "0002_job_scheduled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (表名, 旧索引名, 新索引名)：新名存在则删旧名，否则改名过去
RENAMES = [
    ("ad_accounts", "ix_status_frozen", "ix_ad_accounts_status_frozen"),
    ("campaigns", "ix_ad_account_id", "ix_campaigns_ad_account_id"),
    ("campaigns", "ix_status", "ix_campaigns_status"),
    ("ad_groups", "ix_ad_group_campaign_id", "ix_ad_groups_campaign_id"),
    ("ads", "ix_ad_ad_group_id", "ix_ads_ad_group_id"),
    ("ads", "ix_ad_status", "ix_ads_status"),
    ("risk_events", "ix_risk_event_account_id", "ix_risk_events_ad_account_id"),
    ("risk_events", "ix_event_type", "ix_risk_events_event_type"),
    ("risk_events", "ix_is_resolved", "ix_risk_events_is_resolved"),
    ("risk_events", "ix_risk_level", "ix_risk_events_risk_level"),
    ("account_insights", "ix_account_date", "ix_account_insights_account_date"),
    ("campaign_insights", "ix_campaign_date", "ix_campaign_insights_campaign_date"),
    ("ad_insights", "ix_ad_date", "ix_ad_insights_ad_date"),
]

# 历史遗留的重复索引：新名索引已存在，旧名索引是同一列上的冗余副本
DROP_DUPLICATES = [
    "ix_account_id",        # 冗余于 ix_ad_accounts_account_id
    "ix_campaign_id",       # 冗余于 ix_campaigns_campaign_id
    "ix_ad_group_id",       # 冗余于 ix_ad_groups_ad_group_id
    "ix_ad_id",             # 冗余于 ix_ads_ad_id
    "ix_date",              # 冗余于 ix_account_insights_date
]

# 兜底补建：(索引名, 表名, 列)，缺了才建
ENSURE = [
    ("ix_account_insights_date", "account_insights", "date"),
    ("ix_campaign_insights_date", "campaign_insights", "date"),
    ("ix_ad_insights_date", "ad_insights", "date"),
    # meta_account_id 是后加的列，存量表上没有对应索引
    ("ix_ad_accounts_meta_account_id", "ad_accounts", "meta_account_id"),
]


def _index_exists(name: str) -> bool:
    """判断 public schema 下是否存在该索引"""
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'i' AND n.nspname = 'public' AND c.relname = :name"
        ),
        {"name": name},
    ).first()
    return row is not None


def upgrade() -> None:
    for _table, old, new in RENAMES:
        if _index_exists(new):
            # 新名索引已存在（历史 index=True 隐式建出的），旧名索引属于冗余
            op.execute(f"DROP INDEX IF EXISTS {old}")
        else:
            op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")

    for old in DROP_DUPLICATES:
        op.execute(f"DROP INDEX IF EXISTS {old}")

    for index, table, column in ENSURE:
        if not _index_exists(index):
            op.execute(f"CREATE INDEX {index} ON {table} ({column})")


def downgrade() -> None:
    for index, _table, _column in ENSURE:
        op.execute(f"DROP INDEX IF EXISTS {index}")

    for _table, old, new in reversed(RENAMES):
        if not _index_exists(old) and _index_exists(new):
            op.execute(f"ALTER INDEX IF EXISTS {new} RENAME TO {old}")
