### Contents
- [Project Overview: ShopVirge Backend](#project-overview-shopvirge-backend)
    - [Key Technologies](#key-technologies)
    - [Project Structure](#project-structure)
- [Core Concepts & Conventions](#core-concepts--conventions)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing Guidelines](#testing-guidelines)
- [OpenAPI Best Practices](#openapi-best-practices)
- [Pull Request (PR) Description Guidelines](#pull-request-pr-description-guidelines)

### Project Overview: ShopVirge Backend

The `shop_virge_backend` is a FastAPI-based REST API designed to serve and manage shop-related data, including products, categories, orders, and attributes. It serves as the backend for the ShopVirge platform.

#### Key Technologies
- **Framework:** FastAPI
- **Database:** PostgreSQL with SQLAlchemy ORM
- **Migrations:** Alembic (supporting dual branches: `schema` and `data`)
- **Authentication:** OAuth2 with JWT tokens, session-based middleware
- **Deployment:** AWS App Runner (`apprunner.yaml`), Docker
- **Dependencies:** uv (`pyproject.toml` + `uv.lock`)
- **Linting/Formatting:** ruff (config in `pyproject.toml`), enforced by pre-commit
- **Testing:** Pytest (unit and integration tests)
- **Monitoring:** Sentry integration
- **Form Handling:** `pydantic-forms` for dynamic form generation and validation

#### Project Structure
- `server/`: Main application source code.
    - `api/`: API route definitions (`endpoints/`) and dependency injection (`deps.py`).
    - `crud/`: CRUD operations for database models.
    - `db/`: Database configuration, SQLAlchemy models (`models.py`), and session management.
    - `schemas/`: Pydantic models for request/response validation.
    - `exception_handlers/`: Custom FastAPI exception handlers.
    - `mail_templates/`: Jinja2 templates for emails.
- `migrations/`: Alembic migration scripts.
- `tests/`: Test suite, primarily under `unit_tests/`.
- `pyproject.toml` / `uv.lock`: dependency declaration and lockfile (managed with uv).
- `bin/`: CLI tools and helper scripts.

#### Core Concepts & Conventions
- **Database Sessions:** Managed via `DBSessionMiddleware`, making `db` session accessible.
- **Transactional Support:** Use the `@transactional` decorator or the `transactional(db, log)` context manager (from `server.db.database`) for atomic operations. This ensures automatic commit on success and rollback on error, while also disabling `db.session.commit()` inside the block to prevent accidental partial commits.
    ```python
    from server.db import transactional
    from structlog import get_logger

    logger = get_logger(__name__)

    with transactional(db, logger):
        # your atomic code here
        ...
    ```
- **Shop Scoped API:** Many endpoints are scoped by `shop_id` (e.g., `/shops/{shop_id}/products`).
- **Translations:** Support for multi-language content via translation tables (e.g., `ProductTranslationTable`).
- **Development Workflow:**
    - Install with `uv sync --dev`; prefix commands with `uv run` (or activate `.venv`).
    - `PYTHONPATH=.` is still needed for alembic and uvicorn; pytest resolves the repo root via `[tool.pytest.ini_options] pythonpath`.
    - Migrations are automatically applied on server start (via `lifespan` in `main.py`).
    - Configuration via environment variables (see `server/settings.py`).

#### Code Style Guidelines
- **Linting & Formatting:** Use `ruff` for both formatting and linting (line length 120, target py311). `uv run ruff format . && uv run ruff check --fix .`. It replaced the previous black + isort pair; all config lives in `pyproject.toml` under `[tool.ruff]`. Install the hooks once with `uv run pre-commit install` so this runs on every commit.
- **General Style:** Follow [PEP 8](https://peps.python.org/pep-0008/) for general Python coding style.
- **Docstrings:** Adhere to [PEP 257](https://peps.python.org/pep-0257/) for docstring conventions. Use descriptive triple-quoted strings for all modules, classes, and public functions.
- **Naming Conventions:**
    - Classes: `PascalCase` (e.g., `ProductTable`, `CRUDProduct`).
    - Functions, methods, and variables: `snake_case` (e.g., `get_multi`, `shop_id`).
    - Constants: `UPPER_SNAKE_CASE` (e.g., `APP_VERSION`).
- **Indentation:** Use 4 spaces per indentation level.
- **Type Hinting:** Use type hints for all function arguments and return types. `uv run mypy .` is configured in `pyproject.toml` but is **not** a CI gate yet (~1200 pre-existing errors), so don't add new untyped code.
- **Imports:** Sorted by ruff's `I` rules (same grouping isort produced):
    1. Standard library imports.
    2. Related third-party imports.
    3. Local application/library-specific imports.

    Relative imports are banned (`ban-relative-imports = "all"`) — always import from `server.…`.
- **Database Models:** Naming suffix `Table` is preferred for SQLAlchemy models (e.g., `ShopTable`) to distinguish from Pydantic schemas, though some legacy models may not have it (e.g., `Account`, `License`). All models should inherit from `server.db.database.BaseModel`.
- **CRUD:** Use `CRUD<ModelName>` for CRUD class names and `<model_name>_crud` for instances. All CRUD classes typically inherit from `server.crud.base.CRUDBase`.

#### Testing Guidelines
- **Framework:** Use `pytest` for all unit and integration tests (located in `tests/unit_tests/`).
- **Fixtures:** All shared fixtures (e.g., database sessions, application instances, common entities like shops or products) must be placed in `tests/unit_tests/conftest.py` to ensure reusability across the test suite.
- **Data Verification:** Always assert that the data returned by an API or stored in the database matches what was originally set or expected. This is mandatory for all tests that involve creating, updating, or fetching data (e.g., verifying that a created product has the correct name, description, and price).
- **Reproducer Scripts:** For bug fixes, it is recommended to write a reproduction test or script that fails before the fix is applied and passes afterward.


#### OpenAPI Best Practices
- Design-first where feasible: draft or adjust the OpenAPI Description (OAD) before/alongside code to stay within spec capabilities and enable tooling (linting, SDK/docs generation). See: https://learn.openapis.org/best-practices.html
- Keep metadata complete and accurate:
  - Set `title`, `version`, `description`, `termsOfService`, `contact`, and `license`.
  - Define `servers` with variables for environments (e.g., staging, production) when applicable.
- Use consistent naming and structure:
  - Prefer stable, unique `operationId` values; use `<resource>_<action>` patterns (e.g., `products_list`, `product_create`).
  - Be consistent in JSON property casing (this project uses snake_case in APIs). Avoid mixing styles.
  - Group operations with `tags` (e.g., `shops`, `products`, `attributes`) aligned with our routers in `server/api/api.py`.
- Reuse components aggressively:
  - Place shared schemas under `components.schemas` and reference with `$ref` instead of inlining.
  - Define `parameters`, `requestBodies`, `responses`, and `headers` under `components` for reuse (e.g., pagination, sorting, filtering parameters).
- Document request/response bodies rigorously:
  - Provide `examples` and/or `example` for key payloads; prefer `x-examples` or multiple `examples` when showing variants.
  - Include all relevant HTTP status codes with schemas (e.g., `201` for create, `200` for read/update, `204` for delete, `400/401/403/404/409/422` where applicable).
  - Standardize error responses using a consistent schema (prefer `application/problem+json` Problem Details model as implemented via `ProblemDetailException`).
- Parameters and pagination:
  - Clearly specify parameter `in` (path, query, header, cookie), `schema.type`, `format`, `required`, and `description`.
  - Define reusable pagination parameters (e.g., `skip`, `limit`) and sorting/filtering conventions; document allowed fields and formats.
- Data typing and validation:
  - Use `format` (e.g., `uuid`, `date-time`, `email`, `uri`) and `pattern`, `minimum/maximum`, `minLength/maxLength`, `enum` where relevant.
  - Use `nullable`, `default`, and `readOnly/writeOnly` appropriately to express intent.
  - Prefer `oneOf`/`anyOf`/`allOf` sparingly; add discriminator when polymorphism is needed.
- Deprecation & lifecycle:
  - Mark outdated operations or fields with `deprecated: true` and provide migration notes in `description`.
  - Avoid breaking changes; if unavoidable, bump `version` and prefer additive changes (new fields optional by default).
- Documentation quality:
  - Write meaningful `summary` and `description` for every operation, parameter, schema, and property.
  - Add `externalDocs` for extended guides where helpful.
- Consistency with FastAPI implementation:
  - Ensure `response_model`, `status_code`, `responses`, and `tags` in route decorators reflect the OpenAPI Description.
  - Return correct HTTP codes (e.g., `HTTPStatus.CREATED` for POST create) and align with documented responses.
  - Use Pydantic models in `server/schemas/` as the single source for OpenAPI schemas; avoid inline dict responses.
- Tooling and validation:
  - Lint and validate the OAD in CI using tools like Spectral or `openapi-spec-validator`; fail builds on violations.
  - Keep generated docs (`/docs`, `/redoc`) clean: avoid overly broad `Any` types, and ensure examples render without errors.
- Discoverability and DX enhancements (from APIMatic guidance: https://www.apimatic.io/blog/2022/11/14-best-practices-to-write-openapi-for-better-api-consumption):
  - Provide SDK-friendly enums and clear property descriptions; avoid ambiguous types and undocumented `object`.
  - Ensure consistent pagination patterns and error models across endpoints to facilitate code generation.
  - Include concrete examples for auth flows and typical end-to-end requests for core resources (shops, products, orders).

#### Pull Request (PR) Description Guidelines
- **Output Location:** When asked write draft PR descriptions to files within the `.pr_scratches/` directory. Use descriptive filenames like `PR_<feature_name>_<timestamp>.md`.
- **Content Requirements:**
    - **Endpoint Changes:** Clearly document all added, removed, deprecated, and altered endpoints. Include the HTTP method, path, and a brief summary of the change. For **Altered** endpoints, explicitly state or explain that the change is non-breaking and why (e.g., maintaining backward compatibility, only adding optional fields).
    - **Schema & Model Changes:** Document any new, modified, or deleted Pydantic schemas, SQLAlchemy models, or migrations.
    - **New Unit Tests (UTs):** List all new or significantly modified unit tests. Briefly explain what each test covers.
    - **Other Improvements:** You may briefly mention other enhancements (e.g., better logging, performance tweaks, improved error handling). **Keep this section very concise.**
    - **Scope:** Base the description on all changes within the current branch. The first time you create a description for a PR, you must check all changes from the start of the branch (the fork point or the initial commit of the feature). To optimize subsequent resource usage, you should identify a base commit hash and compare it with the current state.
    - **Committed Work Only:** When generating a PR description, always use committed work (comparing base to `HEAD`) and ignore any uncommitted or unstaged changes in the working tree.
    - **Metadata:** Include the base commit hash used for comparison in the PR description file for reference.
