from uuid import UUID

import structlog
from fastapi import APIRouter

from server.api.endpoints.shops.common import shop_or_404
from server.db.models import ShopTable
from server.schemas.shop import (
    ShopCacheStatus,
    ShopConfig,
    ShopLastCompletedOrder,
    ShopLastPendingOrder,
    ShopWithPrices,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/cache-status/{id}",
    response_model=ShopCacheStatus,
    summary="Get shop cache status",
    description="Returns the timestamp of the last data change visible in this shop. Useful for cache invalidation.",
)
def get_cache_status(id: UUID) -> ShopTable:
    return shop_or_404(id)


@router.get(
    "/last-completed-order/{id}",
    response_model=ShopLastCompletedOrder,
    summary="Get timestamp of last completed order",
    description="Returns the timestamp of the most recently completed order for the shop. Used to detect new fulfilments.",
)
def get_last_completed_order(id: UUID) -> ShopTable:
    return shop_or_404(id)


@router.get(
    "/last-pending-order/{id}",
    response_model=ShopLastPendingOrder,
    summary="Get timestamp of last pending order",
    description="Returns the timestamp of the most recently created pending order for the shop. Used by POS displays to detect new incoming orders.",
)
def get_last_pending_order(id: UUID) -> ShopTable:
    return shop_or_404(id)


@router.get(
    "/{id}",
    response_model=ShopWithPrices,
    summary="Get shop",
    description="Retrieve a shop by its UUID, including all associated price records.",
)
def get_by_id(id: UUID) -> ShopTable:
    return shop_or_404(id)


@router.get(
    "/config/{id}",
    response_model=ShopConfig,
    summary="Get shop configuration",
    description="Retrieve the shop's full configuration object, including feature toggles (e.g. stock tracking, checkout behaviour) and payment settings.",
)
def get_config(id: UUID) -> ShopTable:
    return shop_or_404(id)
