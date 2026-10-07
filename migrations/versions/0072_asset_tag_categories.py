"""Categorize asset tags while preserving existing tag and asset IDs."""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0072_asset_tag_categories"
down_revision = "0071_instagram_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "creative_asset_tag_categories",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("tenant_id", sa.String(50), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("selection_mode", sa.String(10), nullable=False, server_default="MULTIPLE"),
        sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_asset_tag_category_tenant_name"),
    )
    op.create_index("ix_creative_asset_tag_categories_tenant_id", "creative_asset_tag_categories", ["tenant_id"])
    op.add_column("creative_asset_tags", sa.Column("category_id", sa.String(50), nullable=True))
    op.add_column("creative_asset_tags", sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"))

    bind = op.get_bind()
    tenant_ids = [row[0] for row in bind.execute(sa.text("SELECT DISTINCT tenant_id FROM creative_asset_tags"))]
    for tenant_id in tenant_ids:
        category_id = uuid.uuid4().hex
        bind.execute(sa.text(
            "INSERT INTO creative_asset_tag_categories "
            "(id, tenant_id, name, selection_mode, status, sort_order) "
            "VALUES (:id, :tenant_id, :name, 'MULTIPLE', 'ACTIVE', 0)"
        ), {"id": category_id, "tenant_id": tenant_id, "name": "未分类"})
        bind.execute(sa.text(
            "UPDATE creative_asset_tags SET category_id = :category_id WHERE tenant_id = :tenant_id"
        ), {"category_id": category_id, "tenant_id": tenant_id})

    with op.batch_alter_table("creative_asset_tags") as batch:
        batch.alter_column("category_id", existing_type=sa.String(50), nullable=False)
        batch.create_foreign_key("fk_asset_tags_category", "creative_asset_tag_categories", ["category_id"], ["id"])
        batch.drop_constraint("uq_creative_asset_tags_tenant_name", type_="unique")
        batch.create_unique_constraint("uq_asset_tags_tenant_category_name", ["tenant_id", "category_id", "name"])
    op.create_index("ix_asset_tags_tenant_category_status", "creative_asset_tags", ["tenant_id", "category_id", "status"])


def downgrade():
    # Duplicate names in different categories cannot fit the old tenant-wide unique key.
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        "SELECT tenant_id, name FROM creative_asset_tags GROUP BY tenant_id, name HAVING COUNT(*) > 1"
    )).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade: category-specific tags share a name")
    op.drop_index("ix_asset_tags_tenant_category_status", table_name="creative_asset_tags")
    with op.batch_alter_table("creative_asset_tags") as batch:
        batch.drop_constraint("uq_asset_tags_tenant_category_name", type_="unique")
        batch.drop_constraint("fk_asset_tags_category", type_="foreignkey")
        batch.drop_column("category_id")
        batch.drop_column("status")
        batch.create_unique_constraint("uq_creative_asset_tags_tenant_name", ["tenant_id", "name"])
    op.drop_index("ix_creative_asset_tag_categories_tenant_id", table_name="creative_asset_tag_categories")
    op.drop_table("creative_asset_tag_categories")
