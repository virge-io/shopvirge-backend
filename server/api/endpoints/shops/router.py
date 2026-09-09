"""Routers exposed by the ``shops`` package, composed from its modules.

``shop_router`` (``PUT/DELETE /shops/{shop_id}``) and ``legacy_id_router`` (the
routes still spelling the shop id ``{id}``) cannot sit under the prefixed shop
tier — their own path *is* the shop segment — so api.py includes them with
their guard spelled out until the path-param rename re-homes them.
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
shop_router = shop.router
legacy_id_router = APIRouter()
legacy_id_router.include_router(config.router)
legacy_id_router.include_router(allowed_ips.router)

__all__ = ["legacy_id_router", "public_router", "router", "shop_router"]
