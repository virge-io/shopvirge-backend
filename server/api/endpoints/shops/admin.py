"""Admin routes of the ``shops`` package: the plan a shop runs on.

``shop_type`` (plan name, trial mode, language and product limits, Stripe access) is what an operator provisions
for a shop, never something a shop sets for itself, so it sits on the admin tier instead of next to
``PUT /shops/config/{shop_id}``. The storefront reads it back from the public config route.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter

from server.api.endpoints.shops.common import shop_or_404
from server.db import db
from server.schemas.shop import ShopType, ShopTypeUpdate

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.put(
    "/{shop_id}/shop-type",
    response_model=ShopType,
    operation_id="update_shop_type",
    summary="Set shop type",
    description=(
        "Replace the shop's type: the plan name, trial mode, language and product limits and Stripe access. "
        "A new shop starts as a one-language trial until this route provisions its plan."
    ),
)
def update_shop_type(shop_id: UUID, item_in: ShopTypeUpdate) -> dict:
    shop = shop_or_404(shop_id)
    shop.shop_type = item_in.model_dump(mode="json")
    db.session.commit()
    logger.info("Updated shop type", shop_id=str(shop_id), shop_type=shop.shop_type)
    return shop.shop_type
