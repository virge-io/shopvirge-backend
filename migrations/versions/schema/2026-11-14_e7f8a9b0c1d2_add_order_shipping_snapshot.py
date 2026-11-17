"""Persist the Stripe payment linkage and delivery address on each order.

Revision ID: e7f8a9b0c1d2
Revises: a6066f0d2ff7
Create Date: 2026-11-14

Existing orders stay NULL: an account's current address cannot reconstruct an
historical delivery address. No Stripe calls or mail delivery occur in this migration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7f8a9b0c1d2"
down_revision = "a6066f0d2ff7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True))
    op.add_column("orders", sa.Column("shipping_address", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "shipping_address")
    op.drop_column("orders", "stripe_payment_intent_id")
