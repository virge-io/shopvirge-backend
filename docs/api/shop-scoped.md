# Shop-scoped endpoints

Almost every resource in ShopVirge belongs to a specific shop. Most of those endpoints live in the domain packages under `server/api/endpoints/` and are mounted under the `/shops/{shop_id}/...` prefix when registered in `server/api/api.py`.

## The pattern

```text
/shops/{shop_id}/<resource>
/shops/{shop_id}/<resource>/{id}
/shops/{shop_id}/<resource>/<sub-resource>/{id}
```

Handlers that accept a `shop_id` path parameter are gated by an auth dependency (`auth_required` or `auth_required_any`), except for the deliberately public storefront reads listed under [Public sub-routers](#public-sub-routers). Which shops a caller may access is determined by their Cognito group membership — see [Authentication](authentication.md).

CRUDs for shop-owned resources use the shop-aware helpers on `CRUDBase`:

- `get_id_by_shop_id(id, shop_id)` — returns 404 if the row exists but belongs to a different shop.
- `get_multi_by_shop_id(shop_id, ...)` — list with filters/sort/pagination scoped to the shop.
- `create_by_shop_id(shop_id, obj_in)` — write with automatic shop linkage.
- `delete_by_shop_id(shop_id, id)` — scoped delete.

## Resource list

The shop-related domain packages under `server/api/endpoints/`:

| File | Resource |
|------|----------|
| `orders/` | Orders — checkout-facing order creation and status management. Mounted at `/orders` instead of `/shops/{shop_id}/orders`. `PATCH /{order_id}` transitions an order to `complete` or `cancelled`: triggers stock deduction (if enabled), a Discord webhook notification, and an order confirmation email. |
| `products/products.py` | Products (public router split out for unauthenticated catalog browsing). When the shop config toggle `force_unique_product_names` is enabled, `POST` and `PUT` reject duplicate `main_name` values with HTTP 409. Each product also carries a `short_id` (12-char UUID prefix) and an optional `sku` for stable, collision-proof PDP URLs. |
| `categories/categories.py` | Categories (public router split out similarly). |
| `tags/tags.py` | Tags. |
| `attributes/attributes.py` | Attributes (e.g. "size"). `GET /{category_id}/available-attributes` returns option counts for a category; pass `?option_id=<uuid>` (repeatable) to filter counts to products matching all selected options (AND logic). |
| `attributes/options.py` | Attribute options (e.g. "Small"). |
| `products/attribute_values.py` | Per-product attribute assignments. |
| `products/product_tags.py` | Product ↔ tag links. |
| `products/prices.py` | Price management. |
| `accounts/shop.py` | Shop-level customer/vendor accounts. |
| `checkout/stripe.py` | Stripe integration for one-time PaymentIntents and subscription create/cancel. |
| `accounts/api_keys.py` | Per-shop API key management (mint, list, revoke). Keys are accepted on MCP-exposed routes via `auth_required_any`. |
| `categories/images.py` | Category image uploads. |
| `images/shop.py` | Generic shop image uploads. |
| `content/info_request.py` | Incoming info requests. The file also exposes the public `POST /info-request/form` endpoint, which uses `pydantic-forms`; see [Forms](forms.md). |
| `checkout/shipping.py` | Shipping cost calculation. |

## Routers by auth posture

`server/api/api.py` declares five *tiers* — routers that carry a guard once —
and every domain package plugs its routers into the tier matching their
posture, so a guard is never repeated per include or per route:

| Tier | Guard | Holds |
|------|-------|-------|
| `public` | none | storefront reads, checkout, system probes |
| `authenticated` | `auth_required` | collection management: `shops`, `orders`, `faq`, `forms`, `early-access` |
| `admin` | `admin_required` | the cross-shop accounts view |
| `shop` | `shop_access_required` | per-shop, Cognito only: accounts, API keys, image uploads |
| `shop_any` | `auth_required_any_for_shop` | per-shop, API key or Cognito — the MCP-exposed CRUD surface |

Two routers are included outside the tiers with their guard spelled out, until
the changes that remove them land: `shops.legacy_id_router` (paths that still
spell the shop id `{id}`) and `orders.per_shop_router` (orders mount at
`/orders`, not under the shop).

Inside a package one module holds one posture — `shops/public.py`,
`shops/collection.py`, `orders/management.py`, `orders/per_shop.py`,
`orders/public.py` — and a handler takes the principal as a parameter only when
its body reads it. `tests/unit_tests/api/test_router_posture.py` sweeps the whole
route table without credentials: every route off the `public`/`shop_public` tiers
must answer 401 and every route on them must not, so the tiers themselves are the
definition of "public" and there is no allowlist to maintain. It also asserts that
no route is shadowed by an earlier one (FastAPI matches in registration order, so
tier order matters).

## Route helpers

`server/api/route_helpers.py` replaces the plumbing that used to be copied into
every handler:

- `get_or_404(crud.get(id), "… not found")` — narrows the `Optional` and raises
  a problem-detail 404. One idiom instead of the two (`raise_status` vs
  `HTTPException`) that produced differently shaped 404 bodies.
- `list_page(crud, page, response, shop_id=…, query=…)` — the filter / sort /
  paginate call plus the `Content-Range` header.
- `page_params_for(crud)` in `server/api/deps.py` — the typed `skip` / `limit` /
  `filter` / `sort` dependency that `list_page` consumes. Same parameter names
  and descriptions as `common_parameters`, so the spec does not change.
