"""Private template ownership. Unknown historical owners stay admin-only."""
from alembic import op
import sqlalchemy as sa

revision = "0066_template_owner"
down_revision = "0065_meta_sync_log_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("campaign_templates", sa.Column("created_by", sa.String(50), nullable=True))
    op.create_index("ix_campaign_templates_tenant_owner", "campaign_templates", ["tenant_id", "created_by"])
    # A job's operator is not necessarily the template creator. Do not infer
    # ownership from historical jobs; admins can clone legacy templates.


def downgrade():
    op.drop_index("ix_campaign_templates_tenant_owner", table_name="campaign_templates")
    op.drop_column("campaign_templates", "created_by")
