"""Add soft-delete columns to PIM tables.

Revision ID: b4e6d8f0a2c3
Revises: a3f5c7d9e1b2
Create Date: 2026-07-01 00:00:00.000000

"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4e6d8f0a2c3"
down_revision = "a3f5c7d9e1b2"
branch_labels = None
depends_on = None

SOFT_DELETE_TABLES = ["products", "categories", "tags", "attributes", "attribute_options"]


def upgrade() -> None:
    for table in SOFT_DELETE_TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"], unique=False)

    op.add_column("products", sa.Column("deleted_batch_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True))
    op.create_index("ix_products_deleted_batch_id", "products", ["deleted_batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_products_deleted_batch_id", table_name="products")
    op.drop_column("products", "deleted_batch_id")
    for table in reversed(SOFT_DELETE_TABLES):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_column(table, "deleted_at")
