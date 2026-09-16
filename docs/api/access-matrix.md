---
title: Access matrix
description: Who may call which route, derived from the route table.
---

# Access matrix

Generated from the route table by `bin/generate_access_matrix.py`; a test fails when this page is stale.
One row per route: the REST columns and the MCP columns describe the same route, reached two ways.

| Cell | Meaning |
|---|---|
| `R` / `W` | the route reads / writes (its HTTP method) and this caller may call it |
| `own` / `any` | shop-scoped: only the caller's own shop(s) / every shop |
| `–` | no access |
| `·` | not an MCP tool |

| Caller | Who |
|---|---|
| Public | no credential |
| API key | a per-shop `sv_` key; bound to the shop it was minted for |
| Member | a signed-in user attached to a shop (Cognito group = shop id) |
| Admin | the `admins` group, or a service (M2M) token |
| MCP viewer / operator | a member calling through the MCP server with that role: viewers read, operators read and write. Without a role a user may do nothing through MCP, admins included |

## Authenticated, not shop-scoped

Any signed-in user, not bound to a shop. Apart from per-user routes such as `my-shops`, these still need a shop in their path or an admin guard.

| Method | Path | MCP tool | Public | API key | Member | Admin | MCP viewer | MCP operator |
|---|---|---|---|---|---|---|---|---|
| POST | `/early-access/` |  | – | – | W | W | · | · |
| POST | `/faq/` |  | – | – | W | W | · | · |
| PUT | `/faq/{faq_id}` |  | – | – | W | W | · | · |
| DELETE | `/faq/{faq_id}` |  | – | – | W | W | · | · |
| GET | `/forms` |  | – | – | R | R | · | · |
| POST | `/forms/{form_key}` |  | – | – | W | W | · | · |
| GET | `/licenses` |  | – | – | R | R | · | · |
| POST | `/licenses` |  | – | – | W | W | · | · |
| GET | `/licenses/{id}` |  | – | – | R | R | · | · |
| PUT | `/licenses/{id}` |  | – | – | W | W | · | · |
| DELETE | `/licenses/{id}` |  | – | – | W | W | · | · |
| GET | `/orders/` |  | – | – | R | R | · | · |
| PUT | `/orders/{order_id}` |  | – | – | W | W | · | · |
| GET | `/shops/` |  | – | – | R | R | · | · |
| POST | `/shops/` |  | – | – | W | W | · | · |
| GET | `/shops/my-shops` | list_my_shops | – | – | R | R | R | R |

## Per shop — API key or Cognito

The MCP surface: a key reaches its own shop, a member their shops, an admin any.

| Method | Path | MCP tool | Public | API key | Member | Admin | MCP viewer | MCP operator |
|---|---|---|---|---|---|---|---|---|
| GET | `/orders/shop/{shop_id}/complete` | list_complete_orders | – | R own | R own | R any | R own | R own |
| GET | `/orders/shop/{shop_id}/pending` | list_pending_orders | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/attribute-options/` | list_attribute_options | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/attribute-options/` | create_attribute_option | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/attribute-options/{option_id}` | get_attribute_option | – | R own | R own | R any | R own | R own |
| PUT | `/shops/{shop_id}/attribute-options/{option_id}` | update_attribute_option | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/attribute-options/{option_id}` | delete_attribute_option | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/attributes/` | list_attributes | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/attributes/` | create_attribute | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/attributes/id/{attribute_id}` | get_attribute | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/attributes/id/{attribute_id}/with-options` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/attributes/name/{name}` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/attributes/with-options` |  | – | R own | R own | R any | · | · |
| PUT | `/shops/{shop_id}/attributes/{attribute_id}` | update_attribute | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/attributes/{attribute_id}` | delete_attribute | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/attributes/{attribute_id}/restore` | restore_attribute | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/attributes/{attribute_id}/revisions/{revision_no}/restore` | restore_attribute_revision | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/attributes/{attribute_id}/with-options` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/categories/` | list_categories | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/categories/` | create_category | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/categories/name/{name}` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/categories/{category_id}` | get_category | – | R own | R own | R any | R own | R own |
| PUT | `/shops/{shop_id}/categories/{category_id}` | update_category | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/categories/{category_id}` | delete_category | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/categories/{category_id}/restore` | restore_category | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/categories/{category_id}/revisions` |  | – | R own | R own | R any | · | · |
| POST | `/shops/{shop_id}/categories/{category_id}/revisions/{revision_no}/restore` | restore_category_revision | – | W own | W own | W any | – | W own |
| PUT | `/shops/{shop_id}/categories/{category_id}/swap` |  | – | W own | W own | W any | · | · |
| GET | `/shops/{shop_id}/product-attribute-values/` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/product-attribute-values/{id}` |  | – | R own | R own | R any | · | · |
| DELETE | `/shops/{shop_id}/product-attribute-values/{id}` | product_attribute_values_delete | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/product-attribute-values/{product_id}` | add_product_attribute_options | – | W own | W own | W any | – | W own |
| PUT | `/shops/{shop_id}/product-attribute-values/{product_id}` | product_attribute_values_replace_for_product | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/products-to-tags/` | list_product_to_tags | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/products-to-tags/` | create_product_to_tag | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/products-to-tags/get_relation_id` | get_product_to_tag_relation_id | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/products-to-tags/{id}` | get_product_to_tag | – | R own | R own | R any | R own | R own |
| PUT | `/shops/{shop_id}/products-to-tags/{product_to_tag_id}` | update_product_to_tag | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/products-to-tags/{product_to_tag_id}` | delete_product_to_tag | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/products/` | list_products | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/products/` | create_product | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/products/with_attributes` |  | – | R own | R own | R any | · | · |
| PUT | `/shops/{shop_id}/products/{product_id}` | update_product | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/products/{product_id}` | delete_product | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/products/{product_id}/restore` | restore_product | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/products/{product_id}/revisions` | list_product_revisions | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/products/{product_id}/revisions/{revision_no}` | get_product_revision | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/products/{product_id}/revisions/{revision_no}/restore` | restore_product_revision | – | W own | W own | W any | – | W own |
| PUT | `/shops/{shop_id}/products/{product_id}/swap` |  | – | W own | W own | W any | · | · |
| GET | `/shops/{shop_id}/revisions` | list_shop_revisions | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/revisions/{revision_id}` | get_revision | – | R own | R own | R any | R own | R own |
| GET | `/shops/{shop_id}/tags/` | list_tags | – | R own | R own | R any | R own | R own |
| POST | `/shops/{shop_id}/tags/` | create_tag | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/tags/name/{name}` |  | – | R own | R own | R any | · | · |
| GET | `/shops/{shop_id}/tags/{tag_id}` | get_tag | – | R own | R own | R any | R own | R own |
| PUT | `/shops/{shop_id}/tags/{tag_id}` | update_tag | – | W own | W own | W any | – | W own |
| DELETE | `/shops/{shop_id}/tags/{tag_id}` | delete_tag | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/tags/{tag_id}/restore` | restore_tag | – | W own | W own | W any | – | W own |
| POST | `/shops/{shop_id}/tags/{tag_id}/revisions/{revision_no}/restore` | restore_tag_revision | – | W own | W own | W any | – | W own |
| GET | `/shops/{shop_id}/trash` |  | – | R own | R own | R any | · | · |

## Per shop — Cognito only

As above, but API keys are refused (key management, accounts, uploads).

| Method | Path | MCP tool | Public | API key | Member | Admin | MCP viewer | MCP operator |
|---|---|---|---|---|---|---|---|---|
| GET | `/shops/allowed-ips/{id}` (deprecated) |  | – | – | R own | R any | · | · |
| POST | `/shops/allowed-ips/{id}` (deprecated) |  | – | – | W own | W any | · | · |
| POST | `/shops/allowed-ips/{id}/remove` (deprecated) |  | – | – | W own | W any | · | · |
| GET | `/shops/allowed-ips/{shop_id}` |  | – | – | R own | R any | · | · |
| POST | `/shops/allowed-ips/{shop_id}` |  | – | – | W own | W any | · | · |
| POST | `/shops/allowed-ips/{shop_id}/remove` |  | – | – | W own | W any | · | · |
| PUT | `/shops/config/{id}` (deprecated) |  | – | – | W own | W any | · | · |
| PUT | `/shops/config/{shop_id}` |  | – | – | W own | W any | · | · |
| PUT | `/shops/{shop_id}` |  | – | – | W own | W any | · | · |
| DELETE | `/shops/{shop_id}` |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/accounts/` |  | – | – | R own | R any | · | · |
| POST | `/shops/{shop_id}/accounts/` |  | – | – | W own | W any | · | · |
| PUT | `/shops/{shop_id}/accounts/{account_id}` |  | – | – | W own | W any | · | · |
| DELETE | `/shops/{shop_id}/accounts/{account_id}` |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/accounts/{id}` |  | – | – | R own | R any | · | · |
| GET | `/shops/{shop_id}/api-keys/` |  | – | – | R own | R any | · | · |
| POST | `/shops/{shop_id}/api-keys/` |  | – | – | W own | W any | · | · |
| DELETE | `/shops/{shop_id}/api-keys/{key_id}` |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/attributes/{attribute_id}/options/` (deprecated) |  | – | – | R own | R any | · | · |
| POST | `/shops/{shop_id}/attributes/{attribute_id}/options/` (deprecated) |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/attributes/{attribute_id}/options/{option_id}` (deprecated) |  | – | – | R own | R any | · | · |
| DELETE | `/shops/{shop_id}/attributes/{attribute_id}/options/{option_id}` (deprecated) |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/categories-images/` |  | – | – | R own | R any | · | · |
| PUT | `/shops/{shop_id}/categories-images/delete/{id}` |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/categories-images/{id}` |  | – | – | R own | R any | · | · |
| PUT | `/shops/{shop_id}/categories-images/{id}` |  | – | – | W own | W any | · | · |
| GET | `/shops/{shop_id}/images/signed-url/{image_name}` |  | – | – | R own | R any | · | · |
| POST | `/shops/{shop_id}/product-attribute-values/` (deprecated) |  | – | – | W own | W any | · | · |

## Admin

Cross-shop management; the `admins` group or a service token.

| Method | Path | MCP tool | Public | API key | Member | Admin | MCP viewer | MCP operator |
|---|---|---|---|---|---|---|---|---|
| GET | `/admin/accounts` |  | – | – | – | R | · | · |
| GET | `/admin/accounts/{id}` |  | – | – | – | R | · | · |
| POST | `/admin/accounts/{id}/link-stripe` |  | – | – | – | W | · | · |
| GET | `/admin/accounts/{id}/stripe-customer` |  | – | – | – | R | · | · |
| POST | `/admin/accounts/{id}/sync-stripe` |  | – | – | – | W | · | · |
| DELETE | `/orders/{order_id}` |  | – | – | – | W | · | · |

## Public

No credential; storefront, checkout and discovery.

| Method | Path | MCP tool | Public | API key | Member | Admin | MCP viewer | MCP operator |
|---|---|---|---|---|---|---|---|---|
| GET | `/.well-known/oauth-authorization-server` |  | R | R | R | R | · | · |
| GET | `/.well-known/oauth-protected-resource` |  | R | R | R | R | · | · |
| POST | `/downloads/send` |  | W | W | W | W | · | · |
| GET | `/downloads/{file_name}` |  | R | R | R | R | · | · |
| GET | `/faq/` |  | R | R | R | R | · | · |
| GET | `/faq/{id}` |  | R | R | R | R | · | · |
| GET | `/health/` |  | R | R | R | R | · | · |
| POST | `/images/delete-temp` |  | W | W | W | W | · | · |
| POST | `/images/move` |  | W | W | W | W | · | · |
| GET | `/images/signed-url/{image_name}` |  | R | R | R | R | · | · |
| POST | `/info-request/form` |  | W | W | W | W | · | · |
| GET | `/licenses/improviser/{improviser_user_id}` |  | R | R | R | R | · | · |
| POST | `/oauth/register` |  | W | W | W | W | · | · |
| POST | `/orders/` |  | W | W | W | W | · | · |
| GET | `/orders/check/{ids}` |  | R | R | R | R | · | · |
| POST | `/orders/quote` |  | W | W | W | W | · | · |
| GET | `/orders/stock/{order_id}` |  | R | R | R | R | · | · |
| GET | `/orders/{id}` |  | R | R | R | R | · | · |
| PATCH | `/orders/{order_id}` |  | W | W | W | W | · | · |
| GET | `/sentry/` |  | R | R | R | R | · | · |
| POST | `/shipping/calculate` |  | W | W | W | W | · | · |
| GET | `/shops/cache-status/{id}` (deprecated) |  | R | R | R | R | · | · |
| GET | `/shops/cache-status/{shop_id}` |  | R | R | R | R | · | · |
| GET | `/shops/config/{id}` (deprecated) |  | R | R | R | R | · | · |
| GET | `/shops/config/{shop_id}` |  | R | R | R | R | · | · |
| GET | `/shops/last-completed-order/{id}` (deprecated) |  | R | R | R | R | · | · |
| GET | `/shops/last-completed-order/{shop_id}` |  | R | R | R | R | · | · |
| GET | `/shops/last-pending-order/{id}` (deprecated) |  | R | R | R | R | · | · |
| GET | `/shops/last-pending-order/{shop_id}` |  | R | R | R | R | · | · |
| GET | `/shops/{id}` (deprecated) |  | R | R | R | R | · | · |
| GET | `/shops/{shop_id}` |  | R | R | R | R | · | · |
| GET | `/shops/{shop_id}/categories/{category_id}/available-attributes` |  | R | R | R | R | · | · |
| GET | `/shops/{shop_id}/categories/{category_id}/products` |  | R | R | R | R | · | · |
| GET | `/shops/{shop_id}/prices/` |  | R | R | R | R | · | · |
| POST | `/shops/{shop_id}/prices/` |  | W | W | W | W | · | · |
| GET | `/shops/{shop_id}/products/{product_id}` | get_product | R | R | R | R | R | R |
| GET | `/shops/{shop_id}/products/{product_id}/with_attributes` | get_product_attributes | R | R | R | R | R | R |
| POST | `/shops/{shop_id}/stripe/` |  | W | W | W | W | · | · |
| POST | `/shops/{shop_id}/stripe/subscription` |  | W | W | W | W | · | · |
| DELETE | `/shops/{shop_id}/stripe/subscription/{subscription_id}` |  | W | W | W | W | · | · |
| POST | `/test-forms/` |  | W | W | W | W | · | · |
