"""Add shipping_fee_inc_btw column to orders.

Revision ID: 8037ea701b64
Revises: 7890fc217968
Create Date: 2026-05-05 20:04:25.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8037ea701b64"
down_revision = "7890fc217968"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("shipping_fee_inc_btw", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "shipping_fee_inc_btw")
