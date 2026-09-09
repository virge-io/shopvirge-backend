"""Routers exposed by the ``images`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.images.public import router as public_router
from server.api.endpoints.images.shop import router as shop_router

__all__ = ["public_router", "shop_router"]
