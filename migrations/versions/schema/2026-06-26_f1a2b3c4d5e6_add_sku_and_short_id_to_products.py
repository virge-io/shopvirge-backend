"""Add sku and short_id to products.

Revision ID: f1a2b3c4d5e6
Revises: c1a2b3d4e5f6
Create Date: 2026-06-26 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sku", sa.String(64), nullable=True))
    op.add_column("products", sa.Column("short_id", sa.String(12), nullable=True))

    # Backfill short_id from first 12 chars of existing UUIDs
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE products SET short_id = LEFT(id::text, 12)"))

    op.alter_column("products", "short_id", nullable=False)
    op.create_index("uq_products_short_id", "products", ["short_id"], unique=True)
    op.create_index(
        "uq_products_shop_sku",
        "products",
        ["shop_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_products_shop_sku", table_name="products")
    op.drop_index("uq_products_short_id", table_name="products")
    op.drop_column("products", "short_id")
    op.drop_column("products", "sku")
