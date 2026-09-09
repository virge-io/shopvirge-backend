"""Attributes and their options."""

from server.api.endpoints.attributes.attributes import router
from server.api.endpoints.attributes.options import deprecated_router as deprecated_options_router
from server.api.endpoints.attributes.options import router as options_router

__all__ = ["deprecated_options_router", "options_router", "router"]
