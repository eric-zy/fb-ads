"""Add reusable region groups and targeting packages."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0059_targeting_packages"
down_revision: Union[str, None] = "0058_meta_audience_exclusion_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_table(name: str, *, package: bool = False) -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(name):
        return
    columns = [
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
    ]
    if package:
        columns.extend([
            sa.Column("targeting_json", sa.JSON(), nullable=False),
            sa.Column("placement_json", sa.JSON(), nullable=False),
            sa.Column("region_group_ids", sa.JSON(), nullable=False),
        ])
    else:
        columns.extend([
            sa.Column("geo_locations", sa.JSON(), nullable=False),
            sa.Column("excluded_geo_locations", sa.JSON(), nullable=False),
        ])
    columns.extend([
        sa.Column("account_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    ])
    op.create_table(name, *columns)
    op.create_index(f"ix_{name}_id", name, ["id"])
    op.create_index(f"ix_{name}_tenant_status", name, ["tenant_id", "status"])


def upgrade() -> None:
    _create_table("region_groups")
    _create_table("targeting_packages", package=True)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("targeting_packages"):
        op.drop_table("targeting_packages")
    if sa.inspect(bind).has_table("region_groups"):
        op.drop_table("region_groups")
