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
"""Centralized helper for resolving the right Stripe API key per shop.

Each :class:`server.db.models.ShopTable` row carries its own
``stripe_secret_key``. Historically callers set ``stripe.api_key`` inline
right before issuing a Stripe call, which scattered the key-resolution
logic across endpoints. These helpers consolidate that pattern so new
code (admin tooling, sync jobs) and the existing checkout/payment
endpoints share one path.
"""

from types import ModuleType
from typing import Any, Dict

import stripe

from server.db.models import Account, ShopTable


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


def configure_for_shop(shop: ShopTable) -> ModuleType:
    """Set ``stripe.api_key`` from the shop's secret key.

    Returns the ``stripe`` module so callers can do
    ``stripe_mod = configure_for_shop(shop); stripe_mod.X.create(...)``
    if they prefer a single name. Most callers can ignore the return
    value and import ``stripe`` directly.

    Raises :class:`StripeNotConfigured` when the shop is ``None`` or its
    ``stripe_secret_key`` is empty.
    """
    if shop is None or not getattr(shop, "stripe_secret_key", None):
        raise StripeNotConfigured(f"Shop {getattr(shop, 'id', None)!s} has no stripe_secret_key configured")
    stripe.api_key = shop.stripe_secret_key
    return stripe


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
    """Configure for the shop and retrieve the Stripe customer as a dict.

    ``stripe.error.StripeError`` (and subclasses) propagate to the
    caller — the admin endpoint translates them into HTTP 502.
    """
    configure_for_shop(shop)
    customer = stripe.Customer.retrieve(customer_id)
    # SDK objects offer ``to_dict_recursive`` in current versions; keep a
    # fallback for SDK subminors that name it differently.
    if hasattr(customer, "to_dict_recursive"):
        return customer.to_dict_recursive()
    return dict(customer)
