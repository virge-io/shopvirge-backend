"""Orders: management, the per-shop lists the MCP tools use, and the checkout/POS flow.

Orders mount at ``/orders`` rather than under ``/shops/{shop_id}``, so
``per_shop_router`` carries ``shop_id`` in its own paths and is included with
its guard spelled out in api.py rather than through the shop tier — until the
pending/complete merge moves it.
"""
