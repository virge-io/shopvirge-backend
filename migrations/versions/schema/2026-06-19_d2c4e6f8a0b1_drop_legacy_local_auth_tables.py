"""Drop legacy local-auth tables.

Removes the pre-Cognito local JWT scaffolding: the ``users``, ``roles``,
``roles_users`` and ``shops_users`` tables, plus the ``orders.completed_by``
foreign key into ``users``. Authentication is now fully Cognito-based and none
of these tables are read or written in any active code path.

Revision ID: d2c4e6f8a0b1
Revises: c1a2b3d4e5f6
Create Date: 2026-06-19 00:00:00.000000

"""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

from server.db import UtcTimestamp

# revision identifiers, used by Alembic.
revision = "d2c4e6f8a0b1"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the FK column on orders first (it references users.id).
    op.drop_column("orders", "completed_by")

    # Drop association tables before the tables they reference.
    op.drop_index(op.f("ix_roles_users_id"), table_name="roles_users")
    op.drop_table("roles_users")

    op.drop_index(op.f("ix_shops_users_id"), table_name="shops_users")
    op.drop_table("shops_users")

    op.drop_index(op.f("ix_users_first_name"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_last_name"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_roles_id"), table_name="roles")
    op.drop_table("roles")


def downgrade() -> None:
    op.create_table(
        "roles",
        sa.Column(
            "id", sqlalchemy_utils.types.uuid.UUIDType(), server_default=sa.text("uuid_generate_v4()"), nullable=False
        ),
        sa.Column("name", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_roles_id"), "roles", ["id"], unique=False)

    op.create_table(
        "users",
        sa.Column(
            "id", sqlalchemy_utils.types.uuid.UUIDType(), server_default=sa.text("uuid_generate_v4()"), nullable=False
        ),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column(
            "created_at", UtcTimestamp(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True
        ),
        sa.Column("confirmed_at", UtcTimestamp(timezone=True), nullable=True),
        sa.Column("mail_offers", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_first_name"), "users", ["first_name"], unique=False)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_last_name"), "users", ["last_name"], unique=False)

    op.create_table(
        "roles_users",
        sa.Column(
            "id", sqlalchemy_utils.types.uuid.UUIDType(), server_default=sa.text("uuid_generate_v4()"), nullable=False
        ),
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
        sa.Column("role_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_roles_users_id"), "roles_users", ["id"], unique=False)

    op.create_table(
        "shops_users",
        sa.Column(
            "id", sqlalchemy_utils.types.uuid.UUIDType(), server_default=sa.text("uuid_generate_v4()"), nullable=False
        ),
        sa.Column("user_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
        sa.Column("shop_id", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shops_users_id"), "shops_users", ["id"], unique=False)

    op.add_column(
        "orders",
        sa.Column("completed_by", sqlalchemy_utils.types.uuid.UUIDType(), nullable=True),
    )
    op.create_foreign_key(None, "orders", "users", ["completed_by"], ["id"])
