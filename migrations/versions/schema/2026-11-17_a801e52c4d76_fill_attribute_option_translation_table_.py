"""Fill attribute option translation table with current data.

Revision ID: a801e52c4d76
Revises: bb538b1e8848
Create Date: 2026-11-17 14:09:16.010136

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a801e52c4d76'
down_revision = 'bb538b1e8848'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO attribute_option_translations (option_id, main_name)
            SELECT id, value_key FROM attribute_options
            """
        )
    )

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM attribute_option_translations
            WHERE option_id IN (SELECT id FROM attribute_options)
            """
        )
    )
