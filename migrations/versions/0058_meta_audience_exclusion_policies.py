"""Add versioned account-level audience exclusion policies."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0058_meta_audience_exclusion_policies"
down_revision: Union[str, None] = "0057_meta_tracking_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    asset_columns = {item["name"] for item in inspector.get_columns("meta_audience_assets")}
    if "last_seen_at" not in asset_columns:
        op.add_column("meta_audience_assets", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    if "sync_status" not in asset_columns:
        op.add_column(
            "meta_audience_assets",
            sa.Column("sync_status", sa.String(20), nullable=False, server_default="ACTIVE"),
        )
    if "meta_time_updated" not in asset_columns:
        op.add_column("meta_audience_assets", sa.Column("meta_time_updated", sa.DateTime(), nullable=True))

    if not inspector.has_table("meta_audience_exclusion_policies"):
        op.create_table(
            "meta_audience_exclusion_policies",
            sa.Column("id", sa.String(50), primary_key=True),
            sa.Column("ad_account_id", sa.String(50), nullable=False),
            sa.Column("meta_audience_asset_id", sa.String(50), nullable=False),
            sa.Column("meta_audience_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("reason_code", sa.String(32), nullable=False, server_default="LEGACY_MIGRATION"),
            sa.Column("reason_note", sa.Text(), nullable=True),
            sa.Column("effective_from", sa.DateTime(), nullable=True),
            sa.Column("effective_until", sa.DateTime(), nullable=True),
            sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(50), nullable=True),
            sa.Column("approved_by", sa.String(50), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("tenant_id", sa.String(50), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["meta_audience_asset_id"], ["meta_audience_assets.id"]),
            sa.UniqueConstraint("ad_account_id", "meta_audience_asset_id", name="uq_meta_audience_policy_asset"),
        )
        op.create_index(
            "ix_meta_audience_policies_id", "meta_audience_exclusion_policies", ["id"]
        )
        op.create_index(
            "ix_meta_audience_policies_ad_account_id", "meta_audience_exclusion_policies", ["ad_account_id"]
        )
        op.create_index(
            "ix_meta_audience_policies_meta_audience_asset_id",
            "meta_audience_exclusion_policies",
            ["meta_audience_asset_id"],
        )
        op.create_index(
            "ix_meta_audience_policies_meta_audience_id",
            "meta_audience_exclusion_policies",
            ["meta_audience_id"],
        )
        op.create_index(
            "ix_meta_audience_policy_tenant_account",
            "meta_audience_exclusion_policies",
            ["tenant_id", "ad_account_id"],
        )
        op.create_index(
            "ix_meta_audience_policy_tenant_status",
            "meta_audience_exclusion_policies",
            ["tenant_id", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("meta_audience_exclusion_policies"):
        op.drop_table("meta_audience_exclusion_policies")
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("meta_audience_assets")}
    for name in ("meta_time_updated", "sync_status", "last_seen_at"):
        if name in columns:
            op.drop_column("meta_audience_assets", name)
