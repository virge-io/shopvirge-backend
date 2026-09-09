"""Routers exposed by the ``content`` package, composed from its modules."""

from fastapi import APIRouter

from server.api.endpoints.content import (
    downloads,
    early_access,
    faq,
    faq_public,
    info_request,
    licenses,
    licenses_public,
)

# authenticated tier
router = APIRouter()
router.include_router(early_access.router, prefix="/early-access", tags=["early-access"])
router.include_router(faq.router, prefix="/faq", tags=["faq"])
router.include_router(licenses.router, prefix="/licenses", tags=["licenses"])

# public tier
public_router = APIRouter()
public_router.include_router(downloads.router, prefix="/downloads", tags=["downloads"])
public_router.include_router(info_request.router, prefix="/info-request", tags=["info-request"])
public_router.include_router(faq_public.router, prefix="/faq", tags=["faq"])
public_router.include_router(licenses_public.router, prefix="/licenses", tags=["licenses"])

__all__ = ["public_router", "router"]
