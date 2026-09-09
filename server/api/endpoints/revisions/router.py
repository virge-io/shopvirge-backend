"""Routers exposed by the ``revisions`` package.

Revision paths hang directly off ``/shops/{shop_id}`` (``/revisions``,
``/products/{product_id}/revisions``, …), so no segment is added here.
"""

from fastapi import APIRouter

from server.api.endpoints.revisions import revisions

# shop_any tier
router = APIRouter()
router.include_router(revisions.router, tags=["shops", "revisions"])

__all__ = ["router"]
