"""保存海外投放对象映射

Revision ID: 0002_delivery_objects
Revises: 0001_connector_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_delivery_objects"
down_revision = "0001_connector_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("connector_delivery_tasks", sa.Column("objects", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("connector_delivery_tasks", "objects")
