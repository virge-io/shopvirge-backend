"""Routers exposed by the ``categories`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.categories.categories import router
from server.api.endpoints.categories.images import router as images_router
from server.api.endpoints.categories.public import router as public_router

__all__ = ["images_router", "public_router", "router"]
