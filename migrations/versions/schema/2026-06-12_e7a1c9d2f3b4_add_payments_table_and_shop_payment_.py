"""add payments table and shop payment provider columns.

Revision ID: e7a1c9d2f3b4
Revises: c1a2b3d4e5f6
Create Date: 2026-06-12 12:00:00.000000

"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op
from sqlalchemy.dialects import postgresql

from server.db.models import UtcTimestamp

# revision identifiers, used by Alembic.
revision = "e7a1c9d2f3b4"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("payment_provider", sa.String(length=32), server_default="stripe", nullable=False),
    )
    op.add_column(
        "shops",
        sa.Column("payment_config", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_table(
        "payments",
        sa.Column(
            "id",
            sqlalchemy_utils.types.uuid.UUIDType(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("shop_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("order_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="created", nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            UtcTimestamp(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "modified_at",
            UtcTimestamp(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_id"), "payments", ["id"], unique=False)
    op.create_index(op.f("ix_payments_shop_id"), "payments", ["shop_id"], unique=False)
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"], unique=False)
    op.create_index(op.f("ix_payments_provider_payment_id"), "payments", ["provider_payment_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_provider_payment_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_order_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_shop_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_column("shops", "payment_config")
    op.drop_column("shops", "payment_provider")
