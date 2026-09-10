"""Routers exposed by the ``images`` package, composed from its modules."""

from fastapi import APIRouter

from server.api.endpoints.images import public, shop

# public tier: platform-wide bucket helpers
public_router = APIRouter()
public_router.include_router(public.router, prefix="/images", tags=["images"])

# shop_cognito tier (relative to /shops/{shop_id}): per-shop signed upload URL
shop_router = APIRouter()
shop_router.include_router(shop.router, prefix="/images", tags=["shops", "images"])

__all__ = ["public_router", "shop_router"]
