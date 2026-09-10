"""Routers exposed by the ``tags`` package.

Paths here are relative to the ``/shops/{shop_id}`` tier prefix in api.py.
"""

from fastapi import APIRouter

from server.api.endpoints.tags import tags

# shop tier
router = APIRouter()
router.include_router(tags.router, prefix="/tags", tags=["shops", "products"])

__all__ = ["router"]
