---
title: Code Style
description: The formatting, linting and type-checking toolchain, and how to run it locally.
---

# Code style

The project uses a small, opinionated toolchain. All settings live in `pyproject.toml`.

## At a glance

| Tool | Config | Purpose |
|------|--------|---------|
| [ruff](https://docs.astral.sh/ruff/) | `[tool.ruff]` | Formatting **and** linting. Line length **120**, target Python 3.11. |
| [mypy](https://mypy.readthedocs.io/) | `[tool.mypy]` | Static type checking (strict mode). |
| [pre-commit](https://pre-commit.com/) | `.pre-commit-config.yaml` | Runs ruff and a set of hygiene hooks on every commit. |

ruff replaces the previous black + isort pair: `ruff format` covers what black
did and the `I` lint rules cover what isort did, from a single config.

## Formatting and linting

Run both before committing:

```bash
uv run ruff format .
uv run ruff check --fix .
```

CI verifies them without modifying files:

```bash
uv run ruff check .
uv run ruff format --check .
```

See `.github/workflows/run-linting-tests.yml`.

Selected rule families are `ASYNC`, `B`, `C`, `D`, `E`, `F`, `I`, `N`, `RET`,
`S`, `T` and `W`; the ignore list and per-file exemptions are in
`[tool.ruff.lint]`. FastAPI's `Depends()`-in-a-default-argument idiom means
`B008` is exempted for everything under `server/api/`.

## Type checking

mypy runs in strict mode:

```bash
uv run mypy .
```

Key strict-mode flags enabled:

- `disallow_untyped_calls`, `disallow_untyped_defs`, `disallow_incomplete_defs`
- `strict_optional`, `strict_equality`
- `warn_no_return`, `warn_unreachable`

Per-module relaxations (untyped decorators on SQLAlchemy `declared_attr` and on
FastAPI route decorators) live in `[[tool.mypy.overrides]]` blocks. Tests are
excluded via `ignore_errors` because of a
[known mypy interaction with pytest fixtures](https://github.com/python/mypy/issues/11027),
and migrations are excluded entirely.

!!! warning "mypy is not yet a CI gate"

    The existing code does not pass strict mode — `uv run mypy .` currently
    reports roughly 1200 errors. mypy is therefore deliberately **not** wired
    into `.pre-commit-config.yaml` or the linting workflow; it is available as a
    local command while the count is driven down. Do not add new untyped code.

## Python target

Python **3.11**, declared as `requires-python` in `pyproject.toml` and pinned in
`.python-version`. Type hints are required on function signatures.

`PYTHONPATH=.` is required for CLI invocations that don't go through pytest
(alembic, uvicorn). pytest picks the repo root up automatically via
`[tool.pytest.ini_options] pythonpath`.

## Pre-commit

`pre-commit` is in the `dev` dependency group. Install the hooks once:

```bash
uv sync --dev
uv run pre-commit install
```

The configured hooks are ruff (check + format), the standard
`pre-commit-hooks` hygiene set (trailing whitespace, end-of-file, JSON/YAML
validity, debug statements, private-key detection), a few `pygrep-hooks`
Python checks, and shellcheck for the `.sh` scripts.

To run them across the whole repo without committing:

```bash
uv run pre-commit run --all-files
```
