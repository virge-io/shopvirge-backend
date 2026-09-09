"""Customer accounts: per-shop, the cross-shop admin view, and per-shop API keys."""

from server.api.endpoints.accounts.admin import router as admin_router
from server.api.endpoints.accounts.api_keys import router as api_keys_router
from server.api.endpoints.accounts.shop import router as shop_router

__all__ = ["admin_router", "api_keys_router", "shop_router"]
