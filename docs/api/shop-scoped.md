# Shop-scoped endpoints

Almost every resource in ShopVirge belongs to a specific shop. Most of those endpoints are implemented in `server/api/endpoints/shop_endpoints/` and mounted under the `/shops/{shop_id}/...` prefix when registered in `server/api/api.py`.

## The pattern

```text
/shops/{shop_id}/<resource>
/shops/{shop_id}/<resource>/{id}
/shops/{shop_id}/<resource>/<sub-resource>/{id}
```

Every handler that accepts a `shop_id` path parameter is gated by an auth dependency (`auth_required` or `auth_required_any`). Which shops a caller may access is determined by their Cognito group membership — see [Authentication](authentication.md).

CRUDs for shop-owned resources use the shop-aware helpers on `CRUDBase`:

- `get_id_by_shop_id(id, shop_id)` — returns 404 if the row exists but belongs to a different shop.
- `get_multi_by_shop_id(shop_id, ...)` — list with filters/sort/pagination scoped to the shop.
- `create_by_shop_id(shop_id, obj_in)` — write with automatic shop linkage.
- `delete_by_shop_id(shop_id, id)` — scoped delete.

## Resource list

The files under `server/api/endpoints/shop_endpoints/`:

| File | Resource |
|------|----------|
| `orders.py` | Orders — checkout-facing order creation and status management. Implemented in `shop_endpoints/`, but mounted at `/orders` instead of `/shops/{shop_id}/orders`. `PATCH /{order_id}` transitions an order to `complete` or `cancelled`: triggers stock deduction (if enabled), a Discord webhook notification, and an order confirmation email. |
| `products.py` | Products (public router split out for unauthenticated catalog browsing). When the shop config toggle `force_unique_product_names` is enabled, `POST` and `PUT` reject duplicate `main_name` values with HTTP 409. Each product also carries a `short_id` (12-char UUID prefix) and an optional `sku` for stable, collision-proof PDP URLs. |
| `categories.py` | Categories (public router split out similarly). |
| `tags.py` | Tags. |
| `attributes.py` | Attributes (e.g. "size"). `GET /{category_id}/available-attributes` returns option counts for a category; pass `?option_id=<uuid>` (repeatable) to filter counts to products matching all selected options (AND logic). |
| `attribute_options.py` | Attribute options (e.g. "Small"). |
| `product_attribute_values.py` | Per-product attribute assignments. |
| `products_to_tags.py` | Product ↔ tag links. |
| `prices.py` | Price management. |
| `accounts.py` | Shop-level customer/vendor accounts. |
| `stripe.py` | Stripe integration for one-time PaymentIntents and subscription create/cancel. |
| `api_keys.py` | Per-shop API key management (mint, list, revoke). Keys are accepted on MCP-exposed routes via `auth_required_any`. |
| `category_images.py` | Category image uploads. |
| `images.py` | Generic shop image uploads. |
| `product_images.py` | Per-product image uploads. |
| `info_request.py` | Incoming info requests. The file also exposes the public `POST /info-request/form` endpoint, which uses `pydantic-forms`; see [Forms](forms.md). |
| `shipping.py` | Shipping cost calculation. |

## Public sub-routers

Some resources expose a dedicated public router for unauthenticated reads (products, categories), so a storefront can render a catalogue without a session. These are mounted alongside the primary router in `server/api/api.py`.
