"""Products and everything hanging off one: tags, attribute values, prices."""

from server.api.endpoints.products.attribute_values import router as attribute_values_router
from server.api.endpoints.products.prices import router as prices_router
from server.api.endpoints.products.product_tags import router as product_tags_router
from server.api.endpoints.products.products import public_router, router

__all__ = ["attribute_values_router", "prices_router", "product_tags_router", "public_router", "router"]
