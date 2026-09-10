"""Routers exposed by the ``accounts`` package, composed from its modules."""

from fastapi import APIRouter

from server.api.endpoints.accounts import admin, api_keys, shop

# shop_cognito tier (relative to /shops/{shop_id}): keys refused — a key must not be
# able to mint another key, and a user must not mint one for a shop they lack.
shop_router = APIRouter()
shop_router.include_router(shop.router, prefix="/accounts", tags=["shops", "accounts"])
shop_router.include_router(api_keys.router, prefix="/api-keys", tags=["shops", "api-keys"])

# admin tier
admin_router = APIRouter()
admin_router.include_router(admin.router, prefix="/admin/accounts", tags=["admin", "accounts"])

__all__ = ["admin_router", "shop_router"]
