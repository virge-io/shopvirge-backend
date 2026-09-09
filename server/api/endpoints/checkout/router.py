"""Routers exposed by the ``checkout`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.checkout.shipping import router as shipping_router
from server.api.endpoints.checkout.stripe import router as stripe_router

__all__ = ["shipping_router", "stripe_router"]
