# Shop-scoped endpoints

Almost every resource in ShopVirge belongs to a specific shop. Most of those endpoints are implemented in `server/api/endpoints/shop_endpoints/` and mounted under the `/shops/{shop_id}/...` prefix when registered in `server/api/api.py`.

The important checkout exception is `orders.py`: it still lives in `shop_endpoints/`, but the router is mounted globally at `/orders`. Orders remain shop-owned through `OrderTable.shop_id` and the posted payload, not through the path prefix.

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
| `orders.py` | Orders — checkout-facing order creation and completion. Implemented in `shop_endpoints/`, but mounted at `/orders` instead of `/shops/{shop_id}/orders`. |
| `products.py` | Products (public router split out for unauthenticated catalog browsing). |
| `categories.py` | Categories (public router split out similarly). |
| `tags.py` | Tags. |
| `attributes.py` | Attributes (e.g. "size"). |
| `attribute_options.py` | Attribute options (e.g. "Small"). |
| `product_attribute_values.py` | Per-product attribute assignments. |
| `products_to_tags.py` | Product ↔ tag links. |
| `prices.py` | Price management. |
| `accounts.py` | Shop-level customer/vendor accounts. |
| `stripe.py` | Stripe integration for one-time PaymentIntents and subscription create/cancel. |
| `category_images.py` | Category image uploads. |
| `images.py` | Generic shop image uploads. |
| `info_request.py` | Incoming info requests. The file also exposes the public `POST /info-request/form` endpoint, which uses `pydantic-forms`; see [Forms](forms.md). |

## Public sub-routers

Some resources expose a dedicated public router for unauthenticated reads (products, categories), so a storefront can render a catalogue without a session. These are mounted alongside the primary router in `server/api/api.py`.
