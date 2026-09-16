"""Routers exposed by the ``products`` package, composed from its modules.

Paths here are relative to the ``/shops/{shop_id}`` tier prefix in api.py.
"""

from fastapi import APIRouter

from server.api.endpoints.products import attribute_values, prices, product_tags, products, public

# shop tier: API key or Cognito
router = APIRouter()
router.include_router(products.router, prefix="/products", tags=["shops", "products"])
router.include_router(product_tags.router, prefix="/products-to-tags", tags=["shops", "products"])
router.include_router(
    attribute_values.router, prefix="/product-attribute-values", tags=["shops", "products", "attributes"]
)

# shop_public tier: storefront reads
public_router = APIRouter()
public_router.include_router(public.router, prefix="/products", tags=["shops", "products"])
public_router.include_router(prices.router, prefix="/prices", tags=["shops"])

__all__ = ["public_router", "router"]
