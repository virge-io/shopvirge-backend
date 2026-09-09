# Testing

Tests live under `tests/unit_tests/` and run against a real PostgreSQL database (`shop-test`), not mocks — the test suite catches migration-incompatible and query-specific regressions that mocks would hide.

## Running the suite

```bash
# All unit tests
uv run pytest tests/unit_tests

# Single file
uv run pytest tests/unit_tests/api/test_products.py

# Single function
uv run pytest tests/unit_tests/api/test_products.py::test_function_name

# With branch coverage
uv run pytest --cov-branch --cov=server tests/unit_tests
```

`server` imports resolve because `[tool.pytest.ini_options] pythonpath = ["."]` in
`pyproject.toml` puts the repo root on `sys.path` — pytest no longer needs a
`PYTHONPATH=.` prefix. (alembic and uvicorn still do.) Drop the `uv run` prefix if
you have already activated `.venv`.

## Test database

Pytest connects to a `shop-test` PostgreSQL database. Create it once locally:

```bash
createdb shop-test -O shop
```

The test harness applies migrations and tears down / recreates fixtures per test — there's nothing you need to run manually between suites.

## Fixtures and factories

- **`tests/unit_tests/conftest.py`** — shared fixtures: app, authenticated client, DB session, shop, user.
- **`tests/unit_tests/factories/`** — [`factory_boy`](https://factoryboy.readthedocs.io/)-style factories for building test data:
    - `shop.py`, `product.py`, `categories.py`, `attribute.py`, `tag.py`, `account.py`, `order.py`.

Prefer factories over inline row construction — they track relationships and keep test data coherent as the schema evolves.

## Test layout

```text
tests/unit_tests/
├── api/          # endpoint-level tests
├── crud/         # CRUD-layer tests
├── factories/    # factory_boy factories
├── scripts/      # test data generation helpers
├── utils/        # test helpers
├── conftest.py
└── test_db.py
```

## CI

Tests run on every push via `.github/workflows/run-unit-tests.yml` on
`ubuntu-latest`, with a `postgres:12.7-alpine` service container whose port is
mapped to the host. The environment is installed with
[`astral-sh/setup-uv`](https://github.com/astral-sh/setup-uv) and `uv sync --dev`;
`UV_LOCKED: true` makes the job fail if `uv.lock` is out of date with
`pyproject.toml`, so remember to commit the lockfile alongside a dependency change.

The CI command is:

```bash
DATABASE_URI=postgresql://shop:shop@localhost/shop-test \
  uv run pytest --cov-branch --cov=server tests/unit_tests
```
