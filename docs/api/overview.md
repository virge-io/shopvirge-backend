---
title: API Overview
description: Route families, handler locations, and the main API entry points in ShopVirge Backend.
---

# API overview

The live API is self-documenting via FastAPI's built-in OpenAPI UI:

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **Raw spec:** `/openapi.json`

Use those for exact parameter shapes, status codes, and example payloads. This page covers the structure of the API and is a pointer to the files that implement it.

## At a glance

- `server/api/api.py` is the router aggregation point.
- Most tenant-owned resources live under `/shops/{shop_id}/...`.
- Checkout orders are the main exception: they are mounted at `/orders`, while still remaining shop-owned in the database.
- For authentication details, see [Authentication](authentication.md).
- For `pydantic-forms` endpoints, see [Forms](forms.md).
- For Stripe and checkout-specific routes, see [Stripe](stripe.md) and [Checkout flow](../architecture/checkout.md).

## Router aggregation

All routers are composed in `server/api/api.py` into a single `api_router`, which `server/main.py` mounts. The main groupings:

=== "System"

    - `health` — `server/api/endpoints/health.py`
    - `sentry_test` — probe Sentry integration
    - `forms` / `test_forms` — `pydantic-forms` support; see [Forms](forms.md)

=== "Global resources"

    - `images`, `licenses`, `downloads` — asset endpoints
    - `faq`, `early_access`, `info_request` — marketing/content, including the public info-request form endpoint
    - `shops` — shop CRUD (not nested under another shop)
    - `admin_accounts` — superuser cross-shop view of accounts and Stripe linkage (`server/api/endpoints/admin_accounts.py`); see [Admin accounts](admin-accounts.md)

=== "Shop-scoped"

    Most tenant-owned resources live under `/shops/{shop_id}/...`.
    The main checkout exception is `orders.py`, which is currently mounted at `/orders` even though orders still belong to a shop.
    See [Shop-scoped endpoints](shop-scoped.md) for the full list and the exception notes.

=== "MCP"

    `/mcp` (off by default; set `MCP_ENABLED=true`) exposes shop CRUD operations as Model Context Protocol tools for LLM clients. See [MCP server](mcp.md).

## FastAPI app metadata

From `server/main.py`:

- `title`: **ShopVirge API**
- `description`: **Backend for ShopVirge Shops.**
- `version`: the `APP_VERSION` constant in `server/main.py`.

`APP_VERSION` must be bumped whenever the API surface changes, and the OpenAPI
snapshot regenerated with `uv run python bin/regenerate_openapi_snapshot.py` —
the drift guard in `tests/unit_tests/test_openapi_version.py` fails otherwise.
(`server/version.py` is unrelated: it exposes a git commit hash and is not the
API version.)

## Error handling

Custom exception handlers are registered in `server/main.py` for:

- `FormException` — raised by the pydantic-forms machinery; handled by
  `pydantic_forms.exception_handlers.fastapi.form_error_handler`.
- `ProblemDetailException` — RFC 7807 style structured errors; handled by
  `server/exception_handlers/generic_exception_handlers.py`.

Uncaught exceptions are captured by `SentryAsgiMiddleware` and forwarded to Sentry (when `SENTRY_DSN` is configured).
