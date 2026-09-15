"""Routers exposed by the ``system`` package, composed from its modules."""

from fastapi import APIRouter

from server.api.endpoints.system import forms, health, mail_test, oauth_discovery, sentry_test, test_forms
from server.settings import mail_settings

# authenticated tier
router = APIRouter()
router.include_router(forms.router, prefix="/forms", tags=["forms"])

# public tier
public_router = APIRouter()
public_router.include_router(oauth_discovery.router, tags=["oauth"])
public_router.include_router(health.router, prefix="/health", tags=["system"])
public_router.include_router(sentry_test.router, prefix="/sentry", tags=["sentry"])
public_router.include_router(test_forms.router, prefix="/test-forms", tags=["test-forms"])
if mail_settings.MAIL_TEST_ENDPOINT_ENABLED:
    public_router.include_router(mail_test.router, prefix="/mail-test", tags=["mail-test"])

__all__ = ["public_router", "router"]
