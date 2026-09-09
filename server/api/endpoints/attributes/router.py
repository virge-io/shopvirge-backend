"""Routers exposed by the ``attributes`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.attributes.attributes import router
from server.api.endpoints.attributes.options import deprecated_router as deprecated_options_router
from server.api.endpoints.attributes.options import router as options_router

__all__ = ["deprecated_options_router", "options_router", "router"]
