---
title: Overview
description: High-level entry point for the ShopVirge Backend documentation site.
---

# ShopVirge Backend

Welcome to the **ShopVirge Backend** documentation.

ShopVirge is a FastAPI REST API for managing shop pricelists, products, categories, orders, and attributes. It uses a multi-tenant architecture where most resources hang off a shop: `/shops/{shop_id}/...`.

## Summary

- Start with [Quickstart](quickstart.md) if you want a local server running quickly.
- Use [API Overview](api/overview.md) to understand the route layout and where handlers live.
- Use [Checkout flow](architecture/checkout.md) for the end-to-end order and Stripe flow between `shop-poc`, this backend, and Stripe.
- Use [Local setup](development/setup.md) for day-to-day development details and troubleshooting.
- Use [`/llms.txt`](llms.txt) for a curated machine-readable index of the most important docs pages.

!!! tip "FastAPI-style live API reference"
    The running server exposes an interactive OpenAPI UI at:

    - **Swagger UI:** `/docs`
    - **ReDoc:** `/redoc`
    - **Raw spec:** `/openapi.json`

    These are generated from the live FastAPI app, so they always match the running code. This site covers the architecture, rationale, and operational details that the OpenAPI spec can't.

## Where to go next

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Quickstart](quickstart.md)**

    Get a local dev server running. Mirrors the content of `README.md`.

-   :material-graph: **[Architecture](architecture/overview.md)**

    Request flow, database layer, two-branch migrations, and C4 diagrams.

-   :material-api: **[API](api/overview.md)**

    Router layout, multi-tenant shop scoping, authentication, email notifications.

-   :material-code-tags-check: **[Development](development/setup.md)**

    Local setup, testing, code style, and writing migrations.

-   :material-source-pull: **[Contributing](contributing.md)**

    Branching, PR workflow, CI gates, and how the docs site is published.

</div>

## About this site

This site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) — the same stack that powers the [FastAPI documentation](https://fastapi.tiangolo.com/). Diagrams are authored with [Mermaid](https://mermaid.js.org/) directly inside Markdown, and the existing drawio C4 diagrams are exported to SVG for the [C4 diagrams](architecture/diagrams.md) page.
