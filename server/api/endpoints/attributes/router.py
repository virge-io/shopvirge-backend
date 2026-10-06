"""Routers exposed by the ``attributes`` package, composed from its modules.

Paths here are relative to the ``/shops/{shop_id}`` tier prefix in api.py.
"""

from fastapi import APIRouter

from server.api.endpoints.attributes import attributes, options

# shop tier
router = APIRouter()
router.include_router(attributes.router, prefix="/attributes", tags=["shops", "attributes"])
router.include_router(options.router, prefix="/attribute-options", tags=["shops", "attributes"])

__all__ = ["router"]
