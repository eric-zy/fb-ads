"""Scope Connector insight snapshots and close canonical account reporting."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0069_connector_insights_tenant"
down_revision: Union[str, None] = "0068_template_collaborators"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("connector_insights_snapshots"):
        return

    columns = {item["name"] for item in inspector.get_columns("connector_insights_snapshots")}
    if "tenant_id" not in columns:
        op.add_column(
            "connector_insights_snapshots",
            sa.Column("tenant_id", sa.String(length=50), nullable=True),
        )

    # Historical snapshots predate tenant scoping.  Recover their tenant from
    # the canonical Meta account where possible; orphaned rows remain hidden
    # from tenant-scoped ORM queries and can be reviewed separately.
    op.execute(sa.text(
        "UPDATE connector_insights_snapshots "
        "SET tenant_id = (SELECT tenant_id FROM ad_accounts "
        "WHERE ad_accounts.account_id = connector_insights_snapshots.account_id LIMIT 1) "
        "WHERE tenant_id IS NULL"
    ))

    indexes = {item["name"] for item in inspector.get_indexes("connector_insights_snapshots")}
    if "ix_connector_insights_snapshots_tenant_created" not in indexes:
        op.create_index(
            "ix_connector_insights_snapshots_tenant_created",
            "connector_insights_snapshots",
            ["tenant_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("connector_insights_snapshots"):
        return
    indexes = {item["name"] for item in inspector.get_indexes("connector_insights_snapshots")}
    if "ix_connector_insights_snapshots_tenant_created" in indexes:
        op.drop_index(
            "ix_connector_insights_snapshots_tenant_created",
            table_name="connector_insights_snapshots",
        )
    columns = {item["name"] for item in inspector.get_columns("connector_insights_snapshots")}
    if "tenant_id" in columns:
        op.drop_column("connector_insights_snapshots", "tenant_id")
