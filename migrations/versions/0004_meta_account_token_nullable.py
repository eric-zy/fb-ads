"""meta_accounts.access_token 改为可空

背景：
    "账号统一管理"改造为三层分离（BM 主账号 / 广告账户 / 凭据）后，
    Access Token 一律加密存入 credentials 表，BM 主表不再承担明文存储职责
    （见 api/meta_accounts.py：创建 BM 时 access_token 写入空串占位）。

    但存量 schema 里该列是 NOT NULL，导致"只建 BM、稍后再绑凭据"的场景被约束卡住。

    历史明文数据仍然保留在列里：CredentialService.resolve_token_for_meta()
    会优先读 credentials 表，读不到才回退本列，因此本迁移不影响既有账户的可用性。

Revision ID: 0004_meta_account_token_nullable
Revises: 0003_unify_index_names
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_meta_account_token_nullable"
down_revision: Union[str, None] = "0003_unify_index_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE meta_accounts ALTER COLUMN access_token DROP NOT NULL")


def downgrade() -> None:
    # 回退前先把 NULL 填成空串，否则 SET NOT NULL 会因存量空值失败
    op.execute("UPDATE meta_accounts SET access_token = '' WHERE access_token IS NULL")
    op.execute("ALTER TABLE meta_accounts ALTER COLUMN access_token SET NOT NULL")
