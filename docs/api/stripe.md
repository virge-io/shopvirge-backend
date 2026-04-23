# Stripe integration

The backend supports per-shop Stripe accounts: every `ShopTable` row carries its own `stripe_secret_key` and `stripe_public_key`. There is no global Stripe key, so every Stripe call has to choose the correct shop first.

For the end-to-end storefront flow, see [Checkout flow](../architecture/checkout.md). This page stays focused on the backend endpoints and the Stripe objects they create.

## Current backend endpoints

The shop-scoped Stripe router lives in `server/api/endpoints/shop_endpoints/stripe.py` and is mounted at `/shops/{shop_id}/stripe`.

### `POST /shops/{shop_id}/stripe`

Creates a one-time `PaymentIntent`.

Inputs:

- `shop_id` path parameter
- `price` query parameter in euro cents
- `account_id` query parameter

Behavior:

- loads the shop
- sets `stripe.api_key = shop.stripe_secret_key`
- reads `Account.details["stripe_customer_id"]`
- creates a `PaymentIntent`
- returns `{"clientSecret": ...}`

Current payment methods:

- `card`
- `ideal`

### `POST /shops/{shop_id}/stripe/subscription`

Creates a Stripe `Subscription` for recurring checkout.

Inputs:

- `shop_id` path parameter
- `account_id` query parameter
- `yearly` query parameter
- request body containing the ordered product UUIDs

Behavior:

- derives Stripe price lookup keys as `monthly-{product_id}` or `yearly-{product_id}`
- calls `stripe.Price.list(lookup_keys=...)`
- creates a subscription with `payment_behavior="default_incomplete"`
- expands `latest_invoice.payment_intent`
- returns:
  - `clientSecret`
  - `subscriptionId`

### `DELETE /shops/{shop_id}/stripe/subscription/{subscription_id}`

Cancels an existing Stripe subscription.

## Customer linkage

The first time a checkout email is seen for a shop, `server/api/endpoints/shop_endpoints/orders.py` creates both:

- a local `Account` row
- a Stripe customer, when `shop.stripe_secret_key` is configured

The Stripe link is stored in:

```python
Account.details["stripe_customer_id"]
```

That ID is then reused by both one-time and subscription checkout.

## Current limitations

- **No webhook handlers yet.** Order completion is driven by the frontend redirect to `/complete/{order_id}`.
- **No local billing or shipping persistence.** Address data stays inside Stripe Elements for now.
- **The routes are publicly callable.** That is currently required by the storefront checkout flow.
- **Exceptions are returned directly from the route handlers.** `except Exception: return e` should be replaced with proper HTTP error mapping.
- **No dedicated customer sync endpoint exists yet.** Checkout only creates the initial Stripe customer link.
