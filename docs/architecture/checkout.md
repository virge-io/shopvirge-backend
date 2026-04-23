# Checkout flow

This page documents the checkout flow exposed by this backend. It focuses on the implementation that exists today: one-time payments, subscriptions, express checkout for one-time payments, and an optional approval-gated flow used by some front-ends.

It also calls out the gaps that still exist, because several checkout concerns are only partially implemented at the moment.

## Scope at a glance

| Flow | Frontend entry point | Stripe object(s) | Current status |
|------|----------------------|------------------|----------------|
| One-time checkout | `src/pages/[lang]/checkout/[id].tsx` | `PaymentIntent` | Implemented |
| Subscription checkout | `src/pages/[lang]/checkout/subscription/[id].tsx` | `Subscription` + `latest_invoice.payment_intent` | Implemented |
| Express checkout | `src/components/checkout/StripeExpressCheckout.tsx` | `PaymentIntent` | Implemented for one-time checkout only |
| Approval-gated checkout | Front-end approval check before order creation | Same as normal checkout after approval | Supported when the front-end implements the approval step |
| Business / B2B checkout | N/A | N/A | Not implemented yet |
| Billing-address persistence | Stripe Elements only | Stripe-managed during payment | Not implemented in the front-end or `shop-backend` |

## Components involved

| Layer | Main files | Responsibility |
|------|------------|----------------|
| Front-end cart | Front-end cart state and validation logic | Validates cart state, enforces a single payment interval, and creates the pending backend order. |
| Front-end checkout pages | Front-end payment pages | Fetch the order, ask the backend for a Stripe client secret, and render Stripe Elements. |
| Front-end Stripe components | Front-end payment UI components | Confirm payment with Stripe and redirect to the completion page. |
| Front-end completion page | Front-end completion UI | Marks the order `complete` or `cancelled`, clears cart state, and cancels subscriptions on failure. |
| Backend order API | `server/api/endpoints/shop_endpoints/orders.py` | Creates accounts and orders, validates stock, updates order status, decrements stock on completion. |
| Backend Stripe API | `server/api/endpoints/shop_endpoints/stripe.py` | Creates PaymentIntents and Subscriptions, cancels subscriptions. |
| Backend prices API | `server/api/endpoints/shop_endpoints/prices.py` | Returns tax-inclusive catalog input data such as `tax_percentage`, `shippable`, recurring prices, and stock. |
| Stripe | Hosted API + Elements | Owns payment confirmation, payment method collection, customer, subscription, and payment state. |

!!! info "Important current behavior"
    The front-end calculates tax-inclusive line totals client-side from the `/shops/{shop_id}/prices` response. The backend validates stock and account linkage, but it does not recalculate the checkout total before creating the Stripe `PaymentIntent` or `Subscription`.

## Whole checkout flow overview

This is the highest-level diagram of the current checkout implementation. It starts in the front-end storefront, shows the split between one-time and subscription checkout, and ends on the completion page updating the backend order.

## Required data by system

### Front-end

The storefront or front-end needs:

- `PRICELIST_SHOP_ID` to know which shop it is rendering.
- Shop config from `getConfigShopsConfigIdGet(...)`, including `stripe_public_key` and config toggles such as `enable_stock_on_products`.
- Cart contents from local storage, including `product_id`, `quantity`, and selected plan (`onetime`, `monthly`, or `yearly`).
- Product pricing data from `/shops/{shop_id}/prices`, especially `price`, `recurring_price_monthly`, `recurring_price_yearly`, `tax_percentage`, and `shippable`.
- Customer email from the cart form.
- `order.id`, `order.account_id`, Stripe `clientSecret`, and optionally `subscriptionId` to continue payment.

### shop-backend

The backend needs:

A `ShopTable` row with:

- `stripe_secret_key`
- `stripe_public_key`
- `vat_standard`, `vat_lower_*`, `vat_special`, `vat_zero`
- `config["toggles"]`

Product rows with:

- one-time/recurring prices
- `tax_category`
- `shippable`
- `stock`
 
An `Account` row per checkout email, where:

- `name` is currently the customer email
- `details["stripe_customer_id"]` links to Stripe when available

An `OrderTable` row containing:

- `order_info`
- `total`
- `status`
- `customer_order_id`
- `notes`

### Stripe

Stripe needs:

- The per-shop secret key from `ShopTable.stripe_secret_key`.
- A Stripe customer ID for the account when available.
- For one-time payments: the final amount in euro cents.

For subscriptions: Stripe price lookup keys derived from product IDs:

- `monthly-{product_id}`
- `yearly-{product_id}`
- Payment details, and optionally address data, collected inside Stripe Elements.

## End-to-end sequences

=== "One-time checkout"

    ```mermaid
    sequenceDiagram
        autonumber
        actor Customer
        participant FE as Front-end cart / checkout
        participant Orders as Orders API
        participant Prices as Prices API
        participant StripeAPI as Stripe API
        participant DB as PostgreSQL
        participant Stripe as Stripe

        Customer->>FE: Enter email and start checkout
        FE->>Orders: Create order
        Orders->>DB: Find or create account
        opt First checkout with Stripe enabled
            Orders->>Stripe: Create customer
            Stripe-->>Orders: Return customer id
            Orders->>DB: Store customer link
        end
        Orders->>DB: Store pending order
        Orders-->>FE: Return order and account

        FE->>Orders: Load order
        FE->>Prices: Load price data
        Prices-->>FE: Return shippable and tax data
        FE->>StripeAPI: Create payment intent
        StripeAPI->>Stripe: Create payment intent
        Stripe-->>StripeAPI: Return client secret
        StripeAPI-->>FE: Return client secret

        FE->>Stripe: Confirm payment
        Stripe-->>Customer: Redirect to completion page
        FE->>Orders: Update order status
        alt completed and stock enabled
            Orders->>DB: Decrement stock once
        end
    ```

    Express checkout uses the same backend order and PaymentIntent flow. Only the final Stripe UI widget differs.

=== "Subscription checkout"

    ```mermaid
    sequenceDiagram
        autonumber
        actor Customer
        participant FE as Front-end cart / subscription checkout
        participant Orders as Orders API
        participant StripeAPI as Stripe API
        participant DB as PostgreSQL
        participant Stripe as Stripe

        Customer->>FE: Choose monthly or yearly plan
        FE->>Orders: Create order
        Orders->>DB: Find or create account and pending order
        Orders-->>FE: Return order and account

        FE->>Orders: Load order
        FE->>StripeAPI: Create subscription
        StripeAPI->>Stripe: Resolve price and create subscription
        Stripe-->>StripeAPI: Return subscription and client secret
        StripeAPI-->>FE: Return client secret and subscription id

        FE->>Stripe: Confirm first payment
        Stripe-->>Customer: Redirect to completion page
        FE->>Orders: Update order status
        opt user cancels or payment fails
            FE->>StripeAPI: Cancel subscription
        end
    ```

## Where checkout data lives today

| Concern | Front-end | `shop-backend` | Stripe | Notes |
|--------|------------|----------------|--------|-------|
| Cart contents and chosen plan | Local storage (`${LOCALSTORAGE_KEY}-cart`) | Persisted into `OrderTable.order_info` and `OrderTable.notes` | Not stored directly | The frontend enforces one payment interval for the whole cart. |
| Customer email | Cart form input | `Account.name`, exposed again as `order.account_name` | `Customer.email` | There is no richer customer profile in checkout yet. |
| Stripe customer link | Not persisted locally | `Account.details["stripe_customer_id"]` | `Customer.id` | Created during order creation when the shop has a Stripe secret key. |
| Billing details | Passed into Stripe Elements as default `name` and `email` | Not persisted | Managed by Stripe during payment confirmation | No backend schema currently stores billing address or company fields. |
| Shipping address | Collected by `AddressElement` only when the order contains shippable products | Not persisted | Managed by Stripe during payment confirmation | The app does not read the address back out of Elements or save it locally. |
| VAT / tax data | Uses `tax_percentage` from `/shops/{shop_id}/prices` to compute gross totals | VAT rates live on `ShopTable`; product tax classification lives on `ProductTable.tax_category` | No explicit VAT breakdown is sent today | Stripe currently receives the final amount, not a detailed tax model. |
| Order state | Checkout page state + URL query params | `OrderTable.status`, `customer_order_id`, `completed_at` | Payment state lives separately on Stripe objects | Completion is driven by the browser redirect, not by webhooks. |
| Subscription state | `subscriptionId` is held in component state and query params during checkout | Stored in `OrderTable.notes` after success | Canonical state is the Stripe `Subscription` | There is no dedicated local subscription table yet. |
| Referral / approval token | Local storage and session storage flags when the front-end uses an approval flow | Not persisted | Not stored | This is a front-end dependency on an external approval API. |

## Important field-level notes

### Billing address

- There is currently no billing-address model in the front-end or `shop-backend`.
- The payment UI supplies `name` and `email` to Stripe via `payment_method_data.billing_details`.
- A business checkout flow with company name, VAT number, or billing address has not been implemented yet.

### Shipping address

- The shipping address UI is conditional. It is only shown when at least one ordered product has `shippable = true`.
- The collected address stays inside the Stripe Elements flow.
- The backend does not store shipping address data, so there is no fulfillment record yet in `OrderTable` or `Account.details`.

### VAT-related data

- Shop-level VAT rates are stored on `ShopTable`.
- Product rows reference a VAT bucket through `ProductTable.tax_category`.
- `prices.py` resolves that into a concrete `tax_percentage` that the frontend uses to calculate gross totals.
- The current Stripe integration does not send VAT as separate line items or tax rates.

### Subscription-related data

- The selected interval starts in the storefront cart.
- Before payment, yearly subscription carts use `OrderTable.notes = "yearly"` as a flag.
- After successful payment, the completion page overwrites `OrderTable.notes` with the Stripe `subscriptionId`.
- Failed or cancelled payments also use `notes` for error text in some flows.

This means `OrderTable.notes` is currently overloaded for at least three different concerns:

- yearly subscription hint before payment
- Stripe subscription ID after successful payment
- human-readable error or cancellation text

## Stripe identifiers and how they are resolved

| Identifier | Produced by | Stored where | How it is used | What is needed to resolve it |
|-----------|-------------|--------------|----------------|------------------------------|
| `stripe_customer_id` | `stripe.Customer.create(...)` in `orders.py` | `Account.details["stripe_customer_id"]` | Attach future PaymentIntents or Subscriptions to the same Stripe customer | `shop_id` to choose the right secret key, then `account_id` to load the account |
| `clientSecret` for one-time checkout | `stripe.PaymentIntent.create(...)` | Not stored | Render and confirm the Payment Element in the browser | `shop_id`, `account_id`, and the final amount in cents |
| `subscriptionId` | `stripe.Subscription.create(...)` | Frontend state during checkout, then `OrderTable.notes` on success | Cancel the subscription or link a completed order to Stripe | `shop_id` and the returned `subscription_id` |
| Stripe price lookup key | Derived in backend from product IDs | Not stored | Resolve recurring Stripe Price rows before creating a subscription | `product_id` plus `yearly = true/false` |
| `latest_invoice.payment_intent.client_secret` | Expanded from `stripe.Subscription.create(...)` | Not stored | Lets the frontend confirm the first subscription payment | The created `Subscription` object with `expand=["latest_invoice.payment_intent"]` |

One important limitation follows from the table above: the backend does not persist Stripe `payment_intent_id` values or webhook event IDs today. That makes post-hoc reconciliation harder than it needs to be.

## Known gaps and follow-ups

The documentation bullets from the checkout issue break down into two groups: what is now documented here, and what still needs implementation work.

### Documented by this page

- The end-to-end checkout flow across the front-end, `shop-backend`, and Stripe.
- Which data each system needs.
- Where billing, shipping, VAT, and subscription data currently lives.
- Mermaid diagrams for the one-time and subscription flows.
- Which Stripe identifiers are available and how they are resolved.

### Still not implemented in code

- Business / B2B checkout.
- Billing-address persistence.
- Shipping-address persistence.
- Explicit VAT modeling in Stripe checkout.
- A dedicated customer-sync endpoint that updates backend account data and Stripe customer data together.
- A dedicated local subscription model.
- Stripe webhooks for server-side completion and reconciliation.

See also [Stripe integration](../api/stripe.md) for the endpoint-level view of the same payment flow.
