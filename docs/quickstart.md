---
title: Quickstart
description: Fastest path to getting the ShopVirge Backend running locally.
---

# Quickstart

Use this page when you want the shortest path from a fresh checkout to a running backend.

## What you get here

- A working local install path sourced directly from `README.md`
- The exact commands the project currently documents for setup and running
- A stable reference page that stays aligned with the repository root README

## Common next steps

- If you need Cognito, local user creation, or common local failure modes, continue to [Local setup](development/setup.md).
- If you need the route map after booting the server, go to [API Overview](api/overview.md).
- If you need the checkout/payment flow, go to [Checkout flow](architecture/checkout.md).

!!! note "Mirrored from `README.md`"
    The content below is pulled directly from the project's `README.md` at build time via [`mkdocs-include-markdown-plugin`](https://github.com/mondeja/mkdocs-include-markdown-plugin). Edit `README.md` at the repo root to change it — do **not** edit this page. Headings are shifted by one level so the README's H1 becomes an H2 here.

{% 
    include-markdown "../README.md"
    heading-offset=1
    rewrite-relative-urls=true
%}
