"""司南外部平台凭据"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = '0016_sinan_credentials'
down_revision: Union[str, None] = '0015_meta_connections'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'sinan_credentials',
        sa.Column('id', sa.String(50), primary_key=True),
        sa.Column('tenant_id', sa.String(50), nullable=False),
        sa.Column('base_url', sa.String(255), nullable=False),
        sa.Column('app_id', sa.String(64), nullable=False),
        sa.Column('account_encrypted', sa.Text(), nullable=False),
        sa.Column('password_encrypted', sa.Text(), nullable=False),
        sa.Column('menu_id', sa.String(128), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_sinan_credentials_tenant_id', 'sinan_credentials', ['tenant_id'])

def downgrade() -> None:
    op.drop_index('ix_sinan_credentials_tenant_id', table_name='sinan_credentials')
    op.drop_table('sinan_credentials')
