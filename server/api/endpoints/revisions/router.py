"""Routers exposed by the ``revisions`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.revisions.revisions import router

__all__ = ["router"]
