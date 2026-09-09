"""Routers exposed by the ``checkout`` package, composed from its modules."""

from fastapi import APIRouter

from server.api.endpoints.checkout import shipping, stripe

# public tier
public_router = APIRouter()
public_router.include_router(shipping.router, prefix="/shipping", tags=["shipping"])

# shop_public tier (relative to /shops/{shop_id})
shop_public_router = APIRouter()
shop_public_router.include_router(stripe.router, prefix="/stripe", tags=["stripe"])

__all__ = ["public_router", "shop_public_router"]
