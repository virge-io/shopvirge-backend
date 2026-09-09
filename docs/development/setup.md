---
title: Local Development Setup
description: Day-to-day local development setup, environment variables, and common fixes.
---

# Local setup

See the [Quickstart](../quickstart.md) for the canonical setup instructions (sourced from `README.md`). This page covers the parts specific to day-to-day development.

## Summary

- Use this page after Quickstart when you need local dev ergonomics rather than just first boot.
- The most common local blockers are missing Postgres databases and placeholder Cognito settings.
- If you are changing docs as well as code, the same local venv can also serve the MkDocs site.

## Prerequisites

- Python **3.11** (declared as `requires-python` in `pyproject.toml` and pinned in `.python-version`).
- [uv](https://docs.astral.sh/uv/) for dependency management. uv will download the right Python for you if it isn't installed.
- PostgreSQL running locally with a `shop` superuser and two databases: `shop` (main) and `shop-test` (for the test suite).

## Virtual environment

```bash
uv sync --dev            # runtime + dev/test tooling, into .venv/
uv sync --all-groups     # the above plus the docs toolchain
```

If you only need the API running (no docs, no tests), `uv sync --no-dev` is enough.

Every command below can be run either inside the venv (`source .venv/bin/activate`)
or prefixed with `uv run`.

## Environment variables

Settings come from `server/settings.py` (Pydantic `BaseSettings`). FastAPI auto-loads a `.env` file if present. Minimum set for a local server:

```bash
SESSION_SECRET=dev-secret-change-me
DATABASE_URI=postgresql://shop:shop@localhost/shop
TESTING=false
```

If you are using Cognito-protected endpoints locally, you also need the real Cognito values (the defaults in `settings.py` are placeholders that will cause 401s):

```bash
AWS_COGNITO_USERPOOL_ID=eu-central-1_xxxxxxx
AWS_COGNITO_CLIENT_ID=<app client id>
AWS_COGNITO_M2M_CLIENT_ID=<m2m client id>
AWS_COGNITO_M2M_CLIENT_SECRET=<m2m client secret>
```

The `AWS_COGNITO_USERPOOL_ID` is the last path segment of the Cognito issuer URL (`https://cognito-idp.<region>.amazonaws.com/<userpool_id>`); the region subdomain gives you `AWS_COGNITO_REGION`.

For the full list of settings (Cognito, Sentry, Stripe, SMTP, S3 buckets, CORS), inspect `server/settings.py` directly — the pydantic model is the source of truth.

## Running the server

```bash
PYTHONPATH=. uvicorn server.main:app --reload --port 8080
```

The startup hook runs `alembic upgrade heads` automatically, so both migration branches are applied.

Visit:

- <http://127.0.0.1:8080/docs> — Swagger UI.
- <http://127.0.0.1:8080/redoc> — ReDoc.
- <http://127.0.0.1:8080/> — the tiny info root route.

## Docs preview

```bash
uv sync --group docs
uv run mkdocs serve
```

Then open <http://127.0.0.1:8000>.

## Troubleshooting

- **`psycopg` / database connection errors on startup:** verify that both `shop` and `shop-test` exist and that `DATABASE_URI` points at the main `shop` database.
- **401s from protected routes in local dev:** the server is up, but Cognito-related env vars are still placeholders. See the Cognito block above.
- **`mkdocs serve` fails because plugins are missing:** install the docs-only dependencies with `uv sync --group docs` or the full toolchain with `uv sync --all-groups`.
- **CI fails with "the lockfile is not up-to-date":** you changed `pyproject.toml` without re-resolving. Run `uv lock` and commit `uv.lock`.
