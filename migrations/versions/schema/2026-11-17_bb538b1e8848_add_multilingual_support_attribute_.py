"""add_multilingual_support_attribute_option.

Revision ID: bb538b1e8848
Revises: f8a9b0c1d2e3
Create Date: 2026-11-17 13:08:53.849620

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'bb538b1e8848'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # attribute_option_translations
    op.create_table(
        "attribute_option_translations",
        sa.Column(
            'id', 
            postgresql.UUID(as_uuid=False), 
            server_default=sa.text('uuid_generate_v4()'), 
            primary_key=True,
            index=True,
        ),
        sa.Column('option_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('attribute_options.id')),
        sa.Column('main_name', sa.String(length=100), nullable=False),
        sa.Column('alt1_name', sa.String(length=100), nullable=True),
        sa.Column('alt2_name', sa.String(length=100), nullable=True),
    )
    op.create_index('ix_attribute_option_translations_main_name', 'attribute_option_translations', ['main_name'])
    op.create_index('ix_attribute_option_translations_alt1_name', 'attribute_option_translations', ['alt1_name'])
    op.create_index('ix_attribute_option_translations_alt2_name', 'attribute_option_translations', ['alt2_name'])


def downgrade() -> None:
    # Drop index and table
    op.drop_index('ix_attribute_option_translations_alt2_name', table_name='attribute_option_translations')
    op.drop_index('ix_attribute_option_translations_alt1_name', table_name='attribute_option_translations')
    op.drop_index('ix_attribute_option_translations_main_name', table_name='attribute_option_translations')
    op.drop_table('attribute_option_translations')
