# Architecture overview

ShopVirge is a FastAPI REST API backed by PostgreSQL via SQLAlchemy 2.0, with a multi-tenant data model where most resources belong to a shop.

## Layers

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Entry point** | `server/main.py` | FastAPI app, middleware stack, lifespan hook (runs alembic on startup). |
| **Routing** | `server/api/api.py` + `server/api/endpoints/` | Top-level router aggregation. Shop-scoped routes live in `server/api/endpoints/shop_endpoints/`. |
| **CRUD** | `server/crud/` | `CRUD<Model>` classes inheriting `CRUDBase` (`server/crud/base.py`). Instances named `<model>_crud`. |
| **Models** | `server/db/models.py` | SQLAlchemy 2.0 models suffixed `Table`, inheriting `BaseModel` from `server/db/database.py`. |
| **Schemas** | `server/schemas/` | Pydantic 2 models for request and response validation. |
| **Settings** | `server/settings.py` | Pydantic `BaseSettings`; loads env vars and `.env`. |
| **Security** | `server/security.py` | AWS Cognito + JWT + `auth_required` dependency. |
| **Email** | `server/mail.py` + `server/mail_templates/{en,nl}/` | Jinja2-rendered transactional email. |

## Multi-tenancy

Almost every resource is scoped to a shop. Shop-scoped endpoints live under `/shops/{shop_id}/...`:

- `/shops/{shop_id}/products`
- `/shops/{shop_id}/categories`
- `/shops/{shop_id}/attributes`
- `/shops/{shop_id}/prices`
- `/shops/{shop_id}/accounts`
- `/shops/{shop_id}/stripe`
- …

Checkout orders are the main exception: they currently live at `/orders`, while still carrying `shop_id` in the payload and database row.

See [Shop-scoped endpoints](../api/shop-scoped.md) for the pattern and the full list.

## Translations

Four domain tables have companion translation tables that carry per-language name and description columns:

- `ProductTable` ↔ `ProductTranslationTable`
- `CategoryTable` ↔ `CategoryTranslationTable`
- `TagTable` ↔ `TagTranslationTable`
- `AttributeTable` ↔ `AttributeTranslationTable`

`CRUDBase` has built-in logic to transparently create, update, and merge these translation rows when the parent row is written.

## External integrations

- **Payments:** Stripe (`server/api/endpoints/shop_endpoints/stripe.py`).
- **Auth:** AWS Cognito (`fastapi-cognito`) — see [Authentication](../api/authentication.md).
- **Error tracking:** Sentry (`SentryAsgiMiddleware` in `server/main.py`).
- **Email:** SMTP, configured via `SMTP_*` env vars; templates under `server/mail_templates/`.
- **Object storage:** AWS S3 buckets for images, downloads, uploads (see `server/settings.py`).

## Starting points in the codebase

- `server/main.py` — app assembly and middleware order.
- `server/api/api.py` — every router the API exposes.
- `server/db/database.py` — session management (`WrappedSession`, `@transactional`).
- `server/crud/base.py` — common CRUD pattern used throughout.
- `server/api/endpoints/shop_endpoints/orders.py` + `server/api/endpoints/shop_endpoints/stripe.py` — checkout persistence and Stripe orchestration; see [Checkout flow](checkout.md).

See [Request flow](request-flow.md) for a sequence diagram of a typical request.
