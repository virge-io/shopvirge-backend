# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ShopVirge Backend — a FastAPI REST API for managing shop pricelists, products, categories, orders, and attributes. Multi-tenant architecture with shop-scoped endpoints (`/shops/{shop_id}/...`).

## Commands

```bash
# Run dev server (hot reload, port 8080)
PYTHONPATH=. uvicorn server.main:app --reload --port 8080

# Run all tests
PYTHONPATH=. pytest tests/unit_tests

# Run single test file
PYTHONPATH=. pytest tests/unit_tests/api/test_products.py

# Run single test function
PYTHONPATH=. pytest tests/unit_tests/api/test_products.py::test_function_name

# Tests with coverage
PYTHONPATH=. pytest --cov-branch --cov=server tests/unit_tests

# Format code
isort . && black .

# Check formatting (CI runs these)
isort -c . && black --check .

# Type checking
mypy .

# Apply migrations
PYTHONPATH=. alembic upgrade heads

# Create schema migration
PYTHONPATH=. alembic revision --autogenerate -m "Description" --head=schema@head --version-path=migrations/versions/schema

# Create data migration
PYTHONPATH=. alembic revision --message "Description"
```

## Architecture

**Request flow:** Request → SessionMiddleware → DBSessionMiddleware → CORS → API Router → Endpoint → CRUD → Database

**Key layers:**
- `server/api/endpoints/` and `server/api/endpoints/shop_endpoints/` — route handlers. Shop-scoped endpoints live in `shop_endpoints/`.
- `server/crud/` — CRUD classes inheriting `CRUDBase` from `server/crud/base.py`. Named `CRUD<Model>` with instances `<model>_crud`.
- `server/db/models.py` — SQLAlchemy models. Suffixed with `Table` (e.g., `ProductTable`). All inherit `BaseModel` from `server.db.database`.
- `server/schemas/` — Pydantic models for request/response validation.
- `server/api/api.py` — aggregates all routers into `api_router`.
- `server/settings.py` — Pydantic `BaseSettings` configuration, loads from env vars / `.env`.

**Database sessions:** Managed via `DBSessionMiddleware`, accessible as `db`. Use `@transactional` decorator or `transactional(db, logger)` context manager for atomic operations.

**Translations:** Multi-language support via translation tables (e.g., `ProductTranslationTable`).

**Migrations:** Alembic with two independent branches — `schema` (in `migrations/versions/schema/`) and `general/data` (in `migrations/versions/general/`). Migrations auto-apply on server startup.

## Code Style

- **Formatter:** black (line length 120), **imports:** isort (profile="black", line length 120)
- Python 3.11, type hints required on function signatures
- `PYTHONPATH=.` required for all CLI commands

## Documentation / Read the Docs

- The backend docs use **MkDocs Material on Read the Docs**.
- Build config lives in `.readthedocs.yaml`; site/navigation config lives in `mkdocs.yml`; docs content lives under `docs/`.
- Preview docs locally with:

```bash
./.venv/bin/python -m mkdocs serve
./.venv/bin/python -m mkdocs build --strict
```

- `mkdocs.yml` should use `READTHEDOCS_CANONICAL_URL` for `site_url`. Do not hardcode canonical URLs to the bare docs domain, because RTD builds multiple versions.
- Current canonical landing path is `/en/latest/` because the repo does not yet have semver release tags. Once RTD `stable` exists, prefer `/en/stable/` for user-facing links and set `stable` as the RTD default version.
- `docs/llms.txt` is the curated machine-readable docs index. Keep it short, high-signal, and aligned with the most important docs pages and current routing behavior.
- Prefer the default RTD-generated `robots.txt`. If a custom one is ever added, preserve RTD hidden-version exclusions; otherwise old/hidden versions may become indexable again.
- If crawler exclusions are needed, the first low-value candidates are `/search/` and `/404.html`, but only via a deliberate custom `robots.txt`.
- Use RTD dashboard redirects only when a public docs page actually moved or was removed. Do not add speculative redirects.
- Important docs pages should have:
  - front matter `title` and `description`
  - exactly one H1
  - a short summary / “at a glance” section near the top
  - examples and troubleshooting entries where they remove ambiguity
- When documenting versions or canonical behavior, verify against current Read the Docs docs instead of relying on memory.

## Authentication

Three auth dependencies in `server/security.py`:

- `auth_required` — Cognito JWT only (user tokens or M2M tokens with `/api` scope). Used on management routes.
- `auth_required_any` — API key **or** Cognito JWT. Used on MCP-exposed CRUD routes (products, categories, tags, attributes).
- `admin_required` — wraps `auth_required`; additionally asserts membership in the Cognito `Admins` group.

API keys have the prefix `sv_` and are issued per shop via `POST /shops/{shop_id}/api-keys/` (Cognito-only). They only reach routes using `auth_required_any` — the full REST surface requires Cognito.

Shop access is determined by Cognito group membership: a user can touch shops whose UUID matches one of their group names. `GET /shops/my-shops` is the single resolution point; individual shop endpoints do not re-enforce this.

Swagger UI Authorize button is wired via `HTTPBearer(auto_error=False)` in `security.py` — paste a Bearer token there to authenticate in `/docs`.

## MCP

The MCP server is off by default. Enable with `MCP_ENABLED=true`. When enabled, `server/main.py` mounts it at `/mcp` via `mount_mcp(app)` after all routers are included.

Tools are **auto-generated from the FastAPI route table** by `fastmcp`. A route is exposed as an MCP tool by:

1. Adding `tags=[AgentTag.EXPOSED]` (plus `AgentTag.LARGE` for list endpoints) to the route decorator.
2. Setting `operation_id="short_snake_case"` — this becomes the tool name (public API contract).
3. Using `Depends(auth_required_any)` so API-key clients can reach it.
4. Writing the docstring for an LLM: state intent, list required params, call out side effects.

Any route not tagged `AgentTag.EXPOSED` is excluded from MCP by default.

When adding or removing MCP-exposed routes, also:
- Bump `APP_VERSION` in `server/main.py`.
- Regenerate `tests/unit_tests/openapi_snapshot.json` (the drift guard test will fail otherwise):
  ```bash
  PYTHONPATH=. pytest tests/unit_tests/test_openapi_snapshot.py --snapshot-update
  ```
- Update `EXPECTED_TOOL_NAMES` in `tests/unit_tests/mcp/test_mcp.py`.

## Testing

- Tests in `tests/unit_tests/` — shared fixtures in `conftest.py`, test data factories in `tests/unit_tests/factories/`
- Test database: `shop-test` (PostgreSQL)
- CI runs tests with a PostgreSQL service container (see `.github/workflows/run-unit-tests.yml`)
