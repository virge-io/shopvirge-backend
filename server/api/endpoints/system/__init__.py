"""Operational and developer routes: health, OAuth discovery, forms, test probes."""

from server.api.endpoints.system.forms import router as forms_router
from server.api.endpoints.system.health import router as health_router
from server.api.endpoints.system.mail_test import router as mail_test_router
from server.api.endpoints.system.oauth_discovery import router as oauth_discovery_router
from server.api.endpoints.system.sentry_test import router as sentry_test_router
from server.api.endpoints.system.test_forms import router as test_forms_router

__all__ = [
    "forms_router",
    "health_router",
    "mail_test_router",
    "oauth_discovery_router",
    "sentry_test_router",
    "test_forms_router",
]
