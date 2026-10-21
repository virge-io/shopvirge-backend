"""Add missing FK indexes.

Revision ID: a6066f0d2ff7
Revises: 05b6de2cba27
Create Date: 2026-10-21

Every translation table was joined and looked up through its foreign key without an index, so each product,
category, tag and attribute translation load was a sequential scan. ``orders.account_id`` (ON DELETE CASCADE)
had none either, and order creation now looks accounts up by ``(shop_id, name)`` in SQL.

Plain ``CREATE INDEX`` is fine here: the tables hold at most a few thousand rows and migrations run inside one
transaction at application start, which rules out ``CONCURRENTLY`` anyway.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a6066f0d2ff7"
down_revision = "05b6de2cba27"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_product_translations_product_id", "product_translations", ["product_id"]),
    ("ix_category_translations_category_id", "category_translations", ["category_id"]),
    ("ix_tag_translations_tag_id", "tag_translations", ["tag_id"]),
    ("ix_attribute_translations_attribute_id", "attribute_translations", ["attribute_id"]),
    ("ix_orders_account_id", "orders", ["account_id"]),
    ("ix_accounts_shop_id_name", "accounts", ["shop_id", "name"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
