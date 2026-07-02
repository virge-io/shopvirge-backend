"""Add revisions table for PIM aggregate snapshots.

Revision ID: a3f5c7d9e1b2
Revises: f1a2b3c4d5e6
Create Date: 2026-07-01 00:00:00.000000

"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a3f5c7d9e1b2"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revisions",
        sa.Column(
            "id",
            sqlalchemy_utils.types.uuid.UUIDType(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("shop_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("source", sa.String(10), server_default="rest", nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "revision_no", name="uq_revision_entity_no"),
    )
    op.create_index(op.f("ix_revisions_id"), "revisions", ["id"], unique=False)
    op.create_index(op.f("ix_revisions_shop_id"), "revisions", ["shop_id"], unique=False)
    op.create_index("ix_revisions_entity", "revisions", ["entity_type", "entity_id", "revision_no"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_revisions_entity", table_name="revisions")
    op.drop_index(op.f("ix_revisions_shop_id"), table_name="revisions")
    op.drop_index(op.f("ix_revisions_id"), table_name="revisions")
    op.drop_table("revisions")
