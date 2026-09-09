"""Routers exposed by the ``orders`` package, composed from its modules.

Orders mount at ``/orders`` rather than under ``/shops/{shop_id}``, so
``per_shop_router`` carries ``shop_id`` in its own paths and api.py includes it
with its guard spelled out — until the pending/complete merge moves it.
"""

from fastapi import APIRouter

from server.api.endpoints.orders import management, per_shop, public

# authenticated tier
router = APIRouter()
router.include_router(management.router, prefix="/orders", tags=["orders"])

# public tier
public_router = APIRouter()
public_router.include_router(public.router, prefix="/orders", tags=["orders"])

# included directly by api.py, see module docstring
per_shop_router = per_shop.router

__all__ = ["per_shop_router", "public_router", "router"]
