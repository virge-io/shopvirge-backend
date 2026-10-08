"""Add ON DELETE CASCADE to shop and shop-owned foreign keys.

Revision ID: d6e7f8a9b0c1
Revises: b4e6d8f0a2c3
Create Date: 2026-10-08 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "b4e6d8f0a2c3"
branch_labels = None
depends_on = None

CASCADE_FOREIGN_KEYS = [
    ("categories", "categories_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("category_translations", "category_translations_category_id_fkey", ["category_id"], "categories", ["id"]),
    ("tags", "tags_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("tag_translations", "tag_translations_tag_id_fkey", ["tag_id"], "tags", ["id"]),
    ("products", "products_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("products", "products_category_id_fkey", ["category_id"], "categories", ["id"]),
    ("product_translations", "product_translations_product_id_fkey", ["product_id"], "products", ["id"]),
    ("products_to_tags", "products_to_tags_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("products_to_tags", "products_to_tags_product_id_fkey", ["product_id"], "products", ["id"]),
    ("products_to_tags", "products_to_tags_tag_id_fkey", ["tag_id"], "tags", ["id"]),
    ("accounts", "accounts_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("orders", "orders_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("licenses", "licenses_order_id_fkey", ["order_id"], "orders", ["id"]),
    ("info_requests", "info_requests_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("info_requests", "info_requests_product_id_fkey", ["product_id"], "products", ["id"]),
    ("attributes", "attributes_shop_id_fkey", ["shop_id"], "shops", ["id"]),
    ("attribute_translations", "attribute_translations_attribute_id_fkey", ["attribute_id"], "attributes", ["id"]),
    ("attribute_options", "attribute_options_attribute_id_fkey", ["attribute_id"], "attributes", ["id"]),
    ("product_attribute_values", "product_attribute_values_product_id_fkey", ["product_id"], "products", ["id"]),
]


def upgrade() -> None:
    for source_table, constraint_name, local_cols, referent_table, remote_cols in CASCADE_FOREIGN_KEYS:
        op.drop_constraint(constraint_name, source_table, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            source_table,
            referent_table,
            local_cols,
            remote_cols,
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for source_table, constraint_name, local_cols, referent_table, remote_cols in reversed(CASCADE_FOREIGN_KEYS):
        op.drop_constraint(constraint_name, source_table, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            source_table,
            referent_table,
            local_cols,
            remote_cols,
        )
