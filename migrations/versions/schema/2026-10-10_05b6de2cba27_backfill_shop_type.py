"""backfill_shop_type.

Revision ID: 05b6de2cba27
Revises: b4e6d8f0a2c3
Create Date: 2026-10-10 14:06:22.778491

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "05b6de2cba27"
down_revision = "b4e6d8f0a2c3"
branch_labels = None
depends_on = None

# The same one-language trial ``ShopType.trial()`` gives a new shop, spelled out so this revision stays valid
# when the schema moves on.
TRIAL_SHOP_TYPE = (
    '{"name": "small", "max_languages": 1, "max_products": 0, "stripe_access": true, "trial_mode": true, '
    '"trial_started": null}'
)


def upgrade() -> None:
    # The public config route serialises ``shop_type`` and fails on the column default ``{}`` that shops created
    # before the trial default still carry (a factory once stored the JSON string "{}" as well).
    op.execute(
        sa.text(
            f"UPDATE shops SET shop_type = '{TRIAL_SHOP_TYPE}'::jsonb "
            "WHERE jsonb_typeof(shop_type) <> 'object' OR shop_type = '{}'::jsonb"
        )
    )


def downgrade() -> None:
    # A backfilled row cannot be told apart from a provisioned trial, so there is nothing to undo.
    pass
