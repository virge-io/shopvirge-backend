"""create api_keys table.

Revision ID: c1a2b3d4e5f6
Revises: 762f0ee89e95
Create Date: 2026-05-20 12:00:00.000000

"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

from server.db.models import UtcTimestamp

# revision identifiers, used by Alembic.
revision = "c1a2b3d4e5f6"
down_revision = "762f0ee89e95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            sqlalchemy_utils.types.uuid.UUIDType(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("shop_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_sub", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            UtcTimestamp(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_used_at", UtcTimestamp(timezone=True), nullable=True),
        sa.Column("revoked_at", UtcTimestamp(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index(op.f("ix_api_keys_id"), "api_keys", ["id"], unique=False)
    op.create_index(op.f("ix_api_keys_shop_id"), "api_keys", ["shop_id"], unique=False)
    op.create_index(op.f("ix_api_keys_prefix"), "api_keys", ["prefix"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_api_keys_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_shop_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_id"), table_name="api_keys")
    op.drop_table("api_keys")
