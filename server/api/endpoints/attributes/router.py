"""Routers exposed by the ``attributes`` package, composed from its modules.

Paths here are relative to the ``/shops/{shop_id}`` tier prefix in api.py.
"""

from fastapi import APIRouter

from server.api.endpoints.attributes import attributes, options, options_deprecated

# shop_any tier
router = APIRouter()
router.include_router(attributes.router, prefix="/attributes", tags=["shops", "attributes"])
router.include_router(options.router, prefix="/attribute-options", tags=["shops", "attributes"])

# shop tier: the deprecated option routes are Cognito only
shop_router = APIRouter()
shop_router.include_router(
    options_deprecated.router, prefix="/attributes/{attribute_id}/options", tags=["shops", "attributes"]
)

__all__ = ["router", "shop_router"]
