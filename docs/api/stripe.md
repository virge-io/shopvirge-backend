# Stripe integration

!!! warning "Partially superseded by the provider-agnostic payments API"
    One-off checkout payments now go through the pluggable provider layer — see [Payments](payments.md). The `/shops/{shop_id}/stripe/` payment-intent route is kept for the legacy frontend but deprecated; `server/payments/stripe.py` wraps the same Stripe machinery behind the `PaymentProvider` interface. Subscriptions and the admin customer tooling described below remain Stripe-only.

The backend supports per-shop Stripe accounts: every `ShopTable` row carries its own `stripe_secret_key` and `stripe_public_key`. There is no global Stripe key — every API call has to pick the right one for the shop being acted on.

## The helper: `server/services/stripe_client.py`

A small module that centralizes key resolution. It does **not** wrap the whole Stripe SDK — callers still `import stripe` and use it directly. The helper exists so `stripe.api_key` is set in exactly one way.

```python
from server.services import stripe_client

stripe_client.configure_for_shop(shop)         # sets stripe.api_key from shop.stripe_secret_key
customer_id = stripe_client.get_customer_id(account)  # reads account.details["stripe_customer_id"]
customer = stripe_client.fetch_customer(shop, customer_id)  # configure + retrieve as dict
```

### Exceptions

| Exception                | Raised when                                                                |
|--------------------------|----------------------------------------------------------------------------|
| `StripeNotConfigured`    | The shop has no `stripe_secret_key` (or shop is `None`).                   |
| `StripeCustomerMissing`  | The account's `details` JSON has no `stripe_customer_id` key.              |

The helper does **not** translate `stripe.error.StripeError` into HTTP errors — that stays the responsibility of the route handler so each endpoint can pick the right status code (typically `502` for upstream errors).

## Where it's used

- `server/api/endpoints/admin_accounts.py` — superuser sync + read-through (see [Admin accounts](admin-accounts.md)).
- `server/api/endpoints/shop_endpoints/stripe.py` — legacy payment intents, subscription create/cancel.
- `server/api/endpoints/shop_endpoints/orders.py` — auto-creates a Stripe customer when a new account first appears in checkout.
- `server/payments/stripe.py` — the `StripeProvider` behind the [provider-agnostic payments API](payments.md).

## Why module-level, not a `StripeClient` instance

The Stripe SDK supports both styles. The codebase has historically used the module-level `stripe.api_key = ...` pattern; the helper preserves that without introducing a new concurrency model. If multi-key concurrency ever becomes a concern (e.g. background workers fanning out across shops), migrating to `stripe.StripeClient(...)` instances becomes a localized refactor of this one module.

## Known follow-ups

- ~~**No webhook handlers yet.**~~ Resolved for payments: `POST /webhooks/payments/stripe/{shop_id}` verifies signed `payment_intent.*` events (see [Payments](payments.md)). Subscription events still have no webhook and are reconciled via the admin sync endpoints.
- **`/shops/{shop_id}/stripe/*` routes are unauthenticated.** Public access is currently required by the frontend checkout flow; revisit once the checkout is reworked to carry a token.
- **`shop_endpoints/stripe.py` swallows exceptions** with `except Exception: return e`, which then mishandles the response. Tracked separately. (The provider-based payments endpoints translate provider errors into proper `400`/`502` responses.)
