"""Routers exposed by the ``categories`` package, composed from its modules.

Paths here are relative to the ``/shops/{shop_id}`` tier prefix in api.py.
"""

from fastapi import APIRouter

from server.api.endpoints.categories import categories, images, public

# shop_any tier
router = APIRouter()
router.include_router(categories.router, prefix="/categories", tags=["categories"])

# shop tier: Cognito only
shop_router = APIRouter()
shop_router.include_router(images.router, prefix="/categories-images", tags=["shops", "categories"])

# shop_public tier
public_router = APIRouter()
public_router.include_router(public.router, prefix="/categories", tags=["categories"])

__all__ = ["public_router", "router", "shop_router"]
