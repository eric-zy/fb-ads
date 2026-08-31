"""新增投放模板 / 实例映射 / 凭据 / Job Center / 审计日志 共 8 张表

对齐设计文档：
  第 3.1/10 节  Campaign Template（核心业务对象）
  第 12/13/14 节 三层实例映射（Template × 账户）
  第 9 节        Credential（Token 加密存储，独立于 BM 表）
  第 17 节      Job / JobItem（Job Center）
  第 41.3 节    Audit Log

前置依赖：本迁移引用但不创建以下存量表（由更早的基线或 init_db 建好）
  ad_accounts / meta_accounts / creative_assets

Revision ID: 0001_campaign_template
Revises:
Create Date: 2026-08-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_campaign_template"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------- Campaign Template ----------------
    op.create_table(
        "campaign_templates",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("objective", sa.String(64), nullable=True),
        sa.Column("buying_type", sa.String(64), nullable=True),
        sa.Column("special_ad_categories", sa.JSON(), nullable=True),
        sa.Column("budget_type", sa.String(32), nullable=True),
        sa.Column("daily_budget", sa.Float(), nullable=True),
        sa.Column("lifetime_budget", sa.Float(), nullable=True),
        sa.Column("bid_strategy", sa.String(64), nullable=True),
        sa.Column("optimization_goal", sa.String(64), nullable=True),
        sa.Column("billing_event", sa.String(64), nullable=True),
        sa.Column("targeting_json", sa.JSON(), nullable=True),
        sa.Column("placement_json", sa.JSON(), nullable=True),
        sa.Column("creative_config_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_campaign_templates_id", "campaign_templates", ["id"])

    # ---------------- Campaign 实例映射 ----------------
    op.create_table(
        "campaign_instances",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("template_id", sa.String(50), nullable=False),
        sa.Column("ad_account_id", sa.String(50), nullable=False),
        sa.Column("meta_campaign_id", sa.String(128), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("meta_status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["campaign_templates.id"]),
        sa.ForeignKeyConstraint(["ad_account_id"], ["ad_accounts.id"]),
        # 幂等基石：同一模板在同一账户只能部署一次
        sa.UniqueConstraint(
            "template_id", "ad_account_id", name="uq_template_account_campaign"
        ),
    )
    op.create_index("ix_campaign_instances_id", "campaign_instances", ["id"])
    op.create_index(
        "ix_campaign_instances_template_id", "campaign_instances", ["template_id"]
    )
    op.create_index(
        "ix_campaign_instances_ad_account_id", "campaign_instances", ["ad_account_id"]
    )
    op.create_index(
        "ix_campaign_instances_meta_campaign_id",
        "campaign_instances",
        ["meta_campaign_id"],
    )

    # ---------------- AdSet 实例 ----------------
    op.create_table(
        "adset_instances",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("campaign_instance_id", sa.String(50), nullable=False),
        sa.Column("meta_adset_id", sa.String(128), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_instance_id"], ["campaign_instances.id"]),
    )
    op.create_index("ix_adset_instances_id", "adset_instances", ["id"])
    op.create_index(
        "ix_adset_instances_campaign_instance_id",
        "adset_instances",
        ["campaign_instance_id"],
    )
    op.create_index(
        "ix_adset_instances_meta_adset_id", "adset_instances", ["meta_adset_id"]
    )

    # ---------------- Ad 实例 ----------------
    op.create_table(
        "ad_instances",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("adset_instance_id", sa.String(50), nullable=False),
        sa.Column("creative_id", sa.String(50), nullable=True),
        sa.Column("meta_ad_id", sa.String(128), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["adset_instance_id"], ["adset_instances.id"]),
        sa.ForeignKeyConstraint(["creative_id"], ["creative_assets.id"]),
    )
    op.create_index("ix_ad_instances_id", "ad_instances", ["id"])
    op.create_index(
        "ix_ad_instances_adset_instance_id", "ad_instances", ["adset_instance_id"]
    )
    op.create_index("ix_ad_instances_meta_ad_id", "ad_instances", ["meta_ad_id"])

    # ---------------- 加密凭据 ----------------
    op.create_table(
        "credentials",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("meta_account_id", sa.String(50), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_type", sa.String(32), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["meta_account_id"], ["meta_accounts.id"]),
    )
    op.create_index("ix_credentials_id", "credentials", ["id"])
    op.create_index(
        "ix_credentials_meta_account_id", "credentials", ["meta_account_id"]
    )

    # ---------------- 批量任务 ----------------
    op.create_table(
        "campaign_jobs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("template_id", sa.String(50), nullable=True),
        sa.Column("action_type", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("total_accounts", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["campaign_templates.id"]),
    )
    op.create_index("ix_campaign_jobs_id", "campaign_jobs", ["id"])
    op.create_index("ix_campaign_jobs_template_id", "campaign_jobs", ["template_id"])
    op.create_index("ix_campaign_jobs_status", "campaign_jobs", ["status"])

    # ---------------- 批量任务子项（每账户一条） ----------------
    op.create_table(
        "campaign_job_items",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("job_id", sa.String(50), nullable=False),
        sa.Column("ad_account_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("campaign_instance_id", sa.String(50), nullable=True),
        sa.Column("meta_campaign_id", sa.String(128), nullable=True),
        sa.Column("adset_ids", sa.JSON(), nullable=True),
        sa.Column("ad_ids", sa.JSON(), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_category", sa.String(32), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["campaign_jobs.id"]),
        sa.ForeignKeyConstraint(["ad_account_id"], ["ad_accounts.id"]),
        sa.ForeignKeyConstraint(["campaign_instance_id"], ["campaign_instances.id"]),
        sa.UniqueConstraint("job_id", "ad_account_id", name="uq_job_account"),
    )
    op.create_index("ix_campaign_job_items_id", "campaign_job_items", ["id"])
    op.create_index("ix_campaign_job_items_job_id", "campaign_job_items", ["job_id"])
    op.create_index(
        "ix_campaign_job_items_ad_account_id", "campaign_job_items", ["ad_account_id"]
    )
    op.create_index("ix_campaign_job_items_status", "campaign_job_items", ["status"])
    op.create_index(
        "ix_job_items_request_hash", "campaign_job_items", ["request_hash"]
    )

    # ---------------- 审计日志 ----------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("user_id", sa.String(50), nullable=True),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("request_data", sa.JSON(), nullable=True),
        sa.Column("response_data", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("campaign_job_items")
    op.drop_table("campaign_jobs")
    op.drop_table("credentials")
    op.drop_table("ad_instances")
    op.drop_table("adset_instances")
    op.drop_table("campaign_instances")
    op.drop_table("campaign_templates")
