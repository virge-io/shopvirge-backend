# Shop-scoped endpoints

Almost every resource in ShopVirge belongs to a specific shop. These endpoints are implemented in `server/api/endpoints/shop_endpoints/` and nested under the `/shops/{shop_id}/...` prefix when registered in `server/api/api.py`.

## The pattern

```text
/shops/{shop_id}/<resource>
/shops/{shop_id}/<resource>/{id}
/shops/{shop_id}/<resource>/<sub-resource>/{id}
```

Every handler that accepts a `shop_id` path parameter also runs it through an authorisation dependency that verifies the caller can access that shop (via `ShopUserTable` or a machine-to-machine token with `/api` scope — see [Authentication](authentication.md)).

CRUDs for shop-owned resources use the shop-aware helpers on `CRUDBase`:

- `get_id_by_shop_id(id, shop_id)` — returns 404 if the row exists but belongs to a different shop.
- `get_multi_by_shop_id(shop_id, ...)` — list with filters/sort/pagination scoped to the shop.
- `create_by_shop_id(shop_id, obj_in)` — write with automatic shop linkage.
- `delete_by_shop_id(shop_id, id)` — scoped delete.

## Resource list

The files under `server/api/endpoints/shop_endpoints/`:

| File | Resource |
|------|----------|
| `orders.py` | Orders — create, complete, list, email confirmation on completion. |
| `payments.py` | Provider-agnostic checkout payments (Mollie, Stripe) — see [Payments](payments.md). |
| `products.py` | Products (public router split out for unauthenticated catalog browsing). |
| `categories.py` | Categories (public router split out similarly). |
| `tags.py` | Tags. |
| `attributes.py` | Attributes (e.g. "size"). |
| `attribute_options.py` | Attribute options (e.g. "Small"). |
| `product_attribute_values.py` | Per-product attribute assignments. |
| `products_to_tags.py` | Product ↔ tag links. |
| `prices.py` | Price management. |
| `accounts.py` | Shop-level customer/vendor accounts. |
| `stripe.py` | Legacy Stripe routes (payment intents, subscriptions) — deprecated for one-off payments in favour of `payments.py`. |
| `category_images.py` | Category image uploads. |
| `images.py` | Generic shop image uploads. |
| `info_request.py` | Incoming info requests. |

## Public sub-routers

Some resources expose a dedicated public router for unauthenticated reads (products, categories), so a storefront can render a catalogue without a session. These are mounted alongside the primary router in `server/api/api.py`.
