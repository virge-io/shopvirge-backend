---
title: Recorded demo backend
description: Prepare, reset and run the dedicated ShopVirge demo database for agent recordings.
---

# Recorded demo backend

Demo mode resets a dedicated database, seeds the fixed-ID demo shop, and
serves the normal API on port 8080 without reload. Every start removes the
demo shop's previous catalog, orders, related data and revisions.

## Setup

```sh
uv sync --dev --locked
createdb -h localhost -U shop -O shop shop_demo
./start.sh demo
# Supply the shop's About text for the next take:
./start.sh demo '# About Demo Shop: second-hand electronics'
```

Stop an existing development backend before starting demo mode. Normal
development continues to use `./start.sh dev`. Demo mode uses `shop_demo` by
default; `DEMO_DATABASE_URI` can select another dedicated database whose name
starts with `shop_demo_`. Other database names are refused before migration
or reset. Avoid passing credentials on the command line; configure the environment.

`./start.sh demo` applies migrations, runs `scripts/seed_demo_shop.py` and
starts uvicorn. The recorder in virge-agents manages this process itself,
refuses an occupied port, and stops only its own process group afterwards.

## Seed configuration

The fixed shop ID is `51799a20-6a7c-4867-9545-fed56051a203`, because Cognito
shop access is granted by a group with that UUID. A reset leaves that shop
with English as the main language and zero products/categories. Unrelated
shops remain untouched; only the migration's empty bootstrap shop is replaced.
Database foreign-key cascades cover related and soft-deleted rows. The reset
is atomic, so a failed recreation does not leave the demo shop half-cleared.

```sh
# Validate built-in config without connecting to a database:
PYTHONPATH=. uv run python scripts/seed_demo_shop.py --check
# Validate a storefront config exported to JSON:
PYTHONPATH=. uv run python scripts/seed_demo_shop.py --config demo-config.json --check
# Use custom config for a standalone reset:
DATABASE_URI=postgresql://shop:shop@localhost/shop_demo \
  PYTHONPATH=. uv run python scripts/seed_demo_shop.py --config demo-config.json
```

`--about` overrides the config's About text, including an explicitly empty
string. Without it, a config file's About text is retained; the built-in
default is empty. `DEMO_SHOP_ABOUT` supplies the default for the CLI, and the
optional second argument to `start.sh demo` supplies it for a recording.

## Shop context and settings

`list_my_shops` includes the main/alt1/alt2 language mapping and enabled flags.
`get_shop_about` exposes each slot's language name and About text. Agents can
therefore write copy using the shop's own context and enabled translations.
These are authenticated, shop-scoped operations: Cognito users need membership
in the shop's UUID group (or platform administration) and the appropriate MCP
reader/operator role. API keys remain restricted to their own shop.

Shop configuration/settings routes retain the guards shown in the generated
[access matrix](../api/access-matrix.md). The demo branch also corrects the
Stripe-key replacement script's path; it does not change checkout behavior.

## Signed product images

`POST /shops/{shop_id}/products/{product_id}/images/upload-url` accepts the
image content type and optional filename, verifies the product belongs to
the shop, and returns a fresh object `key`, upload `url` and signed `fields`.
The caller POSTs the image to that URL and then updates the product image slot.
The agent's own upload tool performs those steps without asking the model to
generate bytes, object names or signed fields. Removing an image clears its
slot rather than deleting S3 objects referenced by older revisions.

Uploads require valid backend AWS credentials, bucket permissions and a
renderer/CDN reading that bucket. The release uses the real signed flow;
there is no anonymous upload bypass. Live bucket/CDN validation is excluded
from demo 1.0 acceptance; mocked signing/upload tests remain required.
