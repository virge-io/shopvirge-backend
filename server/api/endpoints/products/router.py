"""Routers exposed by the ``products`` package, composed from its modules.

Handlers live in the resource modules next to this file; api.py mounts these
routers into the auth tiers with their prefixes and tags.
"""

from server.api.endpoints.products.attribute_values import router as attribute_values_router
from server.api.endpoints.products.prices import router as prices_router
from server.api.endpoints.products.product_tags import router as product_tags_router
from server.api.endpoints.products.products import router
from server.api.endpoints.products.public import router as public_router

__all__ = ["attribute_values_router", "prices_router", "product_tags_router", "public_router", "router"]
