"""Shops: the collection, storefront reads, and per-shop management.

``legacy_id_router`` groups the per-shop routes whose path still spells the
shop id ``{id}`` (config, allowed IPs). It exists only until the path-param
rename, which needs a coordinated shop-editor change.
"""

from fastapi import APIRouter

from server.api.endpoints.shops.allowed_ips import router as _allowed_ips_router
from server.api.endpoints.shops.collection import router as collection_router
from server.api.endpoints.shops.config import router as _config_router
from server.api.endpoints.shops.public import router as public_router
from server.api.endpoints.shops.shop import router as shop_router

legacy_id_router = APIRouter()
legacy_id_router.include_router(_config_router)
legacy_id_router.include_router(_allowed_ips_router)

__all__ = ["collection_router", "legacy_id_router", "public_router", "shop_router"]
