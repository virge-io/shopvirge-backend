"""Convert monetary Float columns to Numeric.

Revision ID: 762f0ee89e95
Revises: 8037ea701b64
Create Date: 2026-05-07 22:30:00.000000

Float was unsuitable for monetary values (binary representation, accumulated
rounding error). All money columns become Numeric(12, 2) and the VAT-rate
columns on shops become Numeric(5, 2). The PostgreSQL ``USING <col>::numeric``
clause performs the in-place cast on existing rows.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "762f0ee89e95"
down_revision = "8037ea701b64"
branch_labels = None
depends_on = None


_MONEY_COLUMNS: list[tuple[str, str]] = [
    ("orders", "total"),
    ("orders", "shipping_fee_inc_btw"),
    ("products", "price"),
    ("products", "discounted_price"),
    ("products", "recurring_price_monthly"),
    ("products", "recurring_price_yearly"),
]

_VAT_RATE_COLUMNS: list[tuple[str, str]] = [
    ("shops", "vat_standard"),
    ("shops", "vat_lower_1"),
    ("shops", "vat_lower_2"),
    ("shops", "vat_lower_3"),
    ("shops", "vat_special"),
    ("shops", "vat_zero"),
]


def upgrade() -> None:
    for table, column in _MONEY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(12, 2),
            existing_type=sa.Float(),
            postgresql_using=f"{column}::numeric(12, 2)",
        )
    for table, column in _VAT_RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Numeric(5, 2),
            existing_type=sa.Float(),
            postgresql_using=f"{column}::numeric(5, 2)",
        )


def downgrade() -> None:
    for table, column in _MONEY_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Float(),
            existing_type=sa.Numeric(12, 2),
            postgresql_using=f"{column}::double precision",
        )
    for table, column in _VAT_RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Float(),
            existing_type=sa.Numeric(5, 2),
            postgresql_using=f"{column}::double precision",
        )
