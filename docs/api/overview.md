# API overview

The live API is self-documenting via FastAPI's built-in OpenAPI UI:

- **Swagger UI:** `/docs`
- **ReDoc:** `/redoc`
- **Raw spec:** `/openapi.json`

Use those for exact parameter shapes, status codes, and example payloads. This page covers the structure of the API and is a pointer to the files that implement it.

## Router aggregation

All routers are composed in `server/api/api.py` into a single `api_router`, which `server/main.py` mounts. The main groupings:

=== "Authentication & users"

    - `login` — `server/api/endpoints/login.py`
    - `users` — `server/api/endpoints/users.py`

=== "System"

    - `health` — `server/api/endpoints/health.py`
    - `sentry_test` — probe Sentry integration
    - `forms` / `test_forms` — pydantic-forms support

=== "Global resources"

    - `images`, `licenses`, `downloads` — asset endpoints
    - `faq`, `early_access`, `info_request` — marketing/content
    - `shops` — shop CRUD (not nested under another shop)
    - `admin_accounts` — superuser cross-shop view of accounts and Stripe linkage (`server/api/endpoints/admin_accounts.py`); see [Admin accounts](admin-accounts.md)

=== "Shop-scoped"

    Everything under `/shops/{shop_id}/...` — see [Shop-scoped endpoints](shop-scoped.md) for the full list.

=== "MCP"

    `/mcp` (off by default; set `MCP_ENABLED=true`) exposes shop CRUD operations as Model Context Protocol tools for LLM clients. See [MCP server](mcp.md).

## FastAPI app metadata

From `server/main.py` (version `0.2.6` at time of writing):

- `title`: **ShopVirge API**
- `description`: **Backend for ShopVirge Shops.**

The version is source-controlled in `server/version.py`.

## Error handling

Custom exception handlers are registered in `server/main.py` for:

- `FormException` — raised by the pydantic-forms machinery.
- `ProblemDetailException` — RFC 7807 style structured errors.

Uncaught exceptions are captured by `SentryAsgiMiddleware` and forwarded to Sentry (when `SENTRY_DSN` is configured).
