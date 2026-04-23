---
title: Admin Accounts & Stripe Reconciliation
description: Cross-shop account inspection endpoints for linking and syncing Stripe customer state.
---

# Admin accounts

Cross-shop endpoints for **investigating local `Account` records and reconciling them with Stripe**. Mounted under `/admin/accounts` (`server/api/endpoints/admin_accounts.py`).

## Why this exists

The standard `/shops/{shop_id}/accounts` routes are scoped to a single shop. Each shop carries its own `stripe_secret_key` on `ShopTable`, so resolving "what does Stripe think about this customer?" requires picking the right key per account. These admin endpoints give a superuser a single-pane view across every shop and a one-call sync for pulling the canonical Stripe state into the local `details` JSON column.

## Authentication

All routes require `Depends(deps.get_current_active_superuser)` — a user whose roles include `admin`. Anonymous calls return **401**; authenticated non-admin calls return **403**.

## Where Stripe state is stored

`AccountTable.details` is a JSON column. Sync writes two convenience keys without disturbing anything else already in the column:

| Key                       | Type   | Written by                                      |
|---------------------------|--------|-------------------------------------------------|
| `stripe_customer_id`      | string | order checkout (auto), `POST /link-stripe`      |
| `stripe_customer`         | object | `POST /sync-stripe` (full Stripe Customer dict) |
| `stripe_synced_at`        | string | `POST /sync-stripe` (ISO 8601 UTC timestamp)    |

There is no schema migration — everything piggybacks on the existing JSON column.

## Endpoints

## Common workflows

### Find accounts that are missing Stripe linkage

```bash
curl -H "Authorization: Bearer $T" \
  'https://api.example.com/admin/accounts?missing_stripe=true&limit=50'
```

### Link an existing Stripe customer manually

1. Call `POST /admin/accounts/{id}/link-stripe` with a known `cus_...` ID.
2. Call `POST /admin/accounts/{id}/sync-stripe` to persist the current Stripe snapshot.

### Inspect live Stripe state without persisting it

Use `GET /admin/accounts/{id}/stripe-customer` when you want a one-off read-through to Stripe before deciding whether to sync.

### `GET /admin/accounts`

List accounts across every shop. Supports the usual `skip` / `limit` / `filter` / `sort` query parameters from `common_parameters`, plus two admin-only filters:

| Query parameter   | Type      | Effect                                                                          |
|-------------------|-----------|---------------------------------------------------------------------------------|
| `shop_id`         | UUID      | Restrict to one shop                                                            |
| `missing_stripe`  | bool      | `true` → only accounts without a `stripe_customer_id`; `false` → only those with one |

Sets `Content-Range: accounts {skip}-{skip+limit}/{count}` for paging.

```bash
curl -H "Authorization: Bearer $T" \
  'https://api.example.com/admin/accounts?missing_stripe=true&limit=50'
```

Response (`200 OK`) is a list of `AdminAccountSchema`:

```json
[
  {
    "id": "f3...",
    "shop_id": "0a...",
    "shop_name": "Demo Shop",
    "name": "Jane Doe",
    "hash_name": null,
    "details": {"stripe_customer_id": "cus_abc"},
    "stripe_customer_id": "cus_abc",
    "stripe_synced_at": null
  }
]
```

### `GET /admin/accounts/{id}`

Single-account detail. Returns the same `AdminAccountSchema` as the list endpoint.

| Status | Meaning                |
|--------|------------------------|
| 200    | OK                     |
| 404    | No such account        |

### `GET /admin/accounts/{id}/stripe-customer`

**Read-through** to Stripe — fetches the live `Customer` object via the account's shop's `stripe_secret_key` and returns it. Does **not** persist anything; if you want to keep the snapshot, call `POST /sync-stripe`.

```json
{
  "account_id": "f3...",
  "stripe_customer_id": "cus_abc",
  "stripe_customer": { "id": "cus_abc", "email": "jane@example.com", "...": "..." }
}
```

| Status | Meaning                                                        |
|--------|----------------------------------------------------------------|
| 200    | OK                                                             |
| 400    | Account has no `stripe_customer_id`, or shop has no secret key |
| 404    | No such account                                                |
| 502    | Stripe API error (e.g. customer not found)                     |

### `POST /admin/accounts/{id}/sync-stripe`

Same as the read-through, plus persists the snapshot into `details["stripe_customer"]` and stamps `details["stripe_synced_at"]`. All other keys in `details` are preserved.

```bash
curl -X POST -H "Authorization: Bearer $T" \
  'https://api.example.com/admin/accounts/f3.../sync-stripe'
```

Response (`200 OK`):

```json
{
  "id": "f3...",
  "stripe_customer_id": "cus_abc",
  "stripe_synced_at": "2026-04-15T22:13:24.123456+00:00",
  "stripe_customer": { "id": "cus_abc", "email": "jane@example.com", "...": "..." }
}
```

Errors mirror `GET /stripe-customer`.

### `POST /admin/accounts/{id}/link-stripe`

Manually attach a Stripe customer id to an account that doesn't have one. Useful for reconciling old records that pre-date the auto-customer-create flow in checkout. Does **not** call Stripe — pair with `POST /sync-stripe` afterwards if you want the full snapshot.

Body:

```json
{ "stripe_customer_id": "cus_abc" }
```

| Status | Meaning                       |
|--------|-------------------------------|
| 200    | OK; returns `AdminAccountSchema` |
| 404    | No such account               |
| 422    | Body validation failed         |

## Known limitations / follow-ups

- The shop-scoped `/shops/{shop_id}/accounts` `GET` and `GET {id}` handlers ignore the `{shop_id}` path parameter, so they currently leak accounts across shops. Fixing that is a separate change; in the meantime use `/admin/accounts?shop_id=...` if you need a shop-scoped admin view.
- The shop-scoped `/shops/{shop_id}/stripe/*` routes are unauthenticated (frontend checkout depends on this; revisit once that flow is reworked).
- No Stripe webhook handlers exist yet — payment events have to be reconciled via the sync endpoints above.
