"""Routers exposed by the ``orders`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.orders.management import router as management_router
from server.api.endpoints.orders.per_shop import router as per_shop_router
from server.api.endpoints.orders.public import router as public_router

__all__ = ["management_router", "per_shop_router", "public_router"]
