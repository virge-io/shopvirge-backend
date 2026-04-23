---
title: Contributing
description: Branching, CI, docs workflow, and Read the Docs publishing notes for ShopVirge Backend.
---

# Contributing

## Branching

- Work from feature branches off `main`.
- Prefix with area (`feat/`, `fix/`, `docs/`, `chore/`) — e.g. `docs/mkdocs`, `fix/available-attributes-filter`.
- Keep branches small. A branch that touches API + migrations + docs is harder to review than three branches that each stay in their lane.

## Pull requests

- Open PRs against `main`.
- Include a short "why" in the description (not just "what" — the diff shows that).
- Make sure CI is green before asking for review.

## CI gates

Three workflows run on push and PR:

| Workflow | File | What it checks |
|----------|------|----------------|
| Unit tests | `.github/workflows/run-unit-tests.yml` | `pytest --cov-branch --cov=server tests/unit_tests` against a Postgres service container. |
| Linting | `.github/workflows/run-linting-tests.yml` | `isort -c . && black --check .` |
| Docs build | `.github/workflows/docs-build.yml` | `mkdocs build --strict` — fails on broken links or config errors. |

The docs workflow only triggers on changes under `docs/`, `mkdocs.yml`, `requirements/docs.txt`, `.readthedocs.yaml`, `README.md`, or the workflow file itself — non-docs PRs don't pay the install cost.

## Editing the docs

1. Preview locally:

    ```bash
    pip install -r requirements/docs.txt
    mkdocs serve
    ```

    Open <http://127.0.0.1:8000>.

2. Run a strict build before pushing — matches CI:

    ```bash
    mkdocs build --strict
    ```

3. The **Quickstart** page is auto-included from `README.md` (via [`mkdocs-include-markdown-plugin`](https://github.com/mondeja/mkdocs-include-markdown-plugin)) — edit `README.md`, not `docs/quickstart.md`.

4. For new architectural diagrams, prefer [Mermaid](https://mermaid.js.org/) blocks directly in the Markdown so they live with the prose. Use drawio only for the C4 diagrams in `docs/diagrams/` — after editing a `.drawio` file, re-run `bin/export-diagrams.sh` and commit the regenerated SVG alongside the source.

## Publishing the docs

The docs site is hosted on [Read the Docs](https://readthedocs.org).

### First-time setup (once per project)

1. Sign in at <https://readthedocs.org> with the GitHub account that owns the repo (or the GitHub organisation account).
2. Click **Import a Project** → select `acidjunk/shop-backend` from the list.
3. RTD detects `.readthedocs.yaml` at the repo root automatically — no extra settings needed.
4. The first build kicks off on import. Subsequent builds trigger via the GitHub webhook RTD installs.
5. (Optional) *Admin → Advanced Settings* lets you set the default branch and configure custom domains.

### Private repositories

Use <https://readthedocs.com> (Read the Docs for Business) instead of the `.org` site. The config file and workflow are identical — only the account and GitHub App authorisation differ.

### After merge

Once the `docs/mkdocs` branch merges into `main`, RTD rebuilds and publishes automatically. The URL will be of the form `https://<project-slug>.readthedocs.io/`. Add it to the repo's GitHub **About** box so it's discoverable.

## Versions and canonical URLs

- The repo currently builds docs with **MkDocs**, not Sphinx.
- `mkdocs.yml` uses `READTHEDOCS_CANONICAL_URL` as `site_url`, so canonical tags follow the domain/version chosen by Read the Docs.
- Read the Docs redirects the root docs URL to the project's **default version**.
- With no semver release tags, `latest` is the only practical canonical landing path.
- Once semver tags exist and a real `stable` version is built, prefer setting **stable** as the RTD default version for user-facing links.
- Hide obsolete versions in Read the Docs rather than keeping every old version indexable; RTD's generated `robots.txt` already disallows hidden versions.
- Keep the default RTD-generated `robots.txt` unless you have a strong reason to replace it. A custom file is served from the default version only and can accidentally drop RTD's hidden-version `Disallow` rules if you do not recreate them yourself.
