"""Bind one-time payment ownership to the order, independent of account relinking."""

from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("stripe_payment_customer_id", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("orders", "stripe_payment_customer_id")
