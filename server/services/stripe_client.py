# Copyright 2024 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Build shop-scoped Stripe clients without changing process-global credentials."""

from typing import Any, Dict, cast

import stripe

from server.db.models import Account, ShopTable

# Stripe is called from inside request handlers. The SDK defaults (80 s per request, no retries) would let a
# slow Stripe keep a worker thread busy long after the customer gave up; bound it and retry once on network
# errors.
STRIPE_TIMEOUT_SECONDS = 20


class StripeNotConfigured(Exception):
    """Raised when a shop has no usable ``stripe_secret_key``."""


class StripeCustomerMissing(Exception):
    """Raised when an account has no ``stripe_customer_id`` linked."""


def is_missing_customer_error(exc: Exception) -> bool:
    """Return whether Stripe rejected the customer parameter as no longer existing."""
    return (
        isinstance(exc, stripe.error.InvalidRequestError)
        and getattr(exc, "param", None) == "customer"
        and getattr(exc, "code", None) == "resource_missing"
    )


def get_api_key(shop: ShopTable | None) -> str:
    """Return the shop's validated secret key without changing Stripe globals.

    Raises:
        StripeNotConfigured: If the shop is missing or has no secret key.
    """
    api_key = getattr(shop, "stripe_secret_key", None)
    if not api_key:
        raise StripeNotConfigured(f"Shop {getattr(shop, 'id', None)!s} has no stripe_secret_key configured")
    return cast(str, api_key)


def get_client(shop: ShopTable | None) -> stripe.StripeClient:
    """Return a client with this shop's credentials, timeout and retry policy."""
    return stripe.StripeClient(
        get_api_key(shop),
        max_network_retries=1,
        http_client=stripe.new_default_http_client(timeout=STRIPE_TIMEOUT_SECONDS),
    )


def get_customer_id(account: Account) -> str:
    """Return the Stripe customer id stored on an account.

    Raises :class:`StripeCustomerMissing` when the account's ``details``
    column is missing or has no ``stripe_customer_id`` key.
    """
    details = getattr(account, "details", None) or {}
    customer_id = details.get("stripe_customer_id") if isinstance(details, dict) else None
    if not customer_id:
        raise StripeCustomerMissing(f"Account {getattr(account, 'id', None)!s} has no stripe_customer_id linked")
    return customer_id


def fetch_customer(shop: ShopTable, customer_id: str) -> Dict[str, Any]:
    """Retrieve the Stripe customer using the shop's own client, returning a dict.

    ``stripe.error.StripeError`` (and subclasses) propagate to the
    caller — the admin endpoint translates them into HTTP 502.
    """
    customer = get_client(shop).customers.retrieve(customer_id)
    # SDK objects offer ``to_dict_recursive`` in current versions; keep a
    # fallback for SDK subminors that name it differently.
    if hasattr(customer, "to_dict_recursive"):
        return customer.to_dict_recursive()
    return dict(customer)
