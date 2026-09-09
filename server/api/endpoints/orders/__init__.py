"""Orders: management, the per-shop lists the MCP tools use, and the checkout/POS flow.

Orders mount at ``/orders`` rather than under ``/shops/{shop_id}``, so
``per_shop_router`` carries ``shop_id`` in its own paths and is included with
its guard spelled out in api.py rather than through the shop tier — until the
pending/complete merge moves it.
"""

from server.api.endpoints.orders.management import router as management_router
from server.api.endpoints.orders.per_shop import router as per_shop_router
from server.api.endpoints.orders.public import router as public_router

__all__ = ["management_router", "per_shop_router", "public_router"]
