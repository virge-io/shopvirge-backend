"""Routers exposed by the ``shops`` package, composed from its modules.

``shop_router`` (``/shops/{shop_id}``, ``/shops/config/{shop_id}``,
``/shops/allowed-ips/{shop_id}``) cannot sit under the prefixed shop tier — its
own path *is* the shop segment — so api.py includes it with its guard spelled out.
"""

from fastapi import APIRouter

from server.api.endpoints.shops import allowed_ips, collection, config, public, shop

# authenticated tier
router = APIRouter()
router.include_router(collection.router, prefix="/shops", tags=["shops"])

# public tier
public_router = APIRouter()
public_router.include_router(public.router, prefix="/shops", tags=["shops"])

# included directly by api.py, see module docstring
shop_router = APIRouter()
shop_router.include_router(shop.router)
shop_router.include_router(config.router)
shop_router.include_router(allowed_ips.router)

__all__ = ["public_router", "router", "shop_router"]
