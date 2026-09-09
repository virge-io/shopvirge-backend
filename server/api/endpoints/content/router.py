"""Routers exposed by the ``content`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.content.downloads import router as downloads_router
from server.api.endpoints.content.early_access import router as early_access_router
from server.api.endpoints.content.faq import public_router as faq_public_router
from server.api.endpoints.content.faq import router as faq_router
from server.api.endpoints.content.info_request import router as info_request_router
from server.api.endpoints.content.licenses import router as licenses_router

__all__ = [
    "downloads_router",
    "early_access_router",
    "faq_public_router",
    "faq_router",
    "info_request_router",
    "licenses_router",
]
