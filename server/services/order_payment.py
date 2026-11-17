"""Verify a server-linked Stripe payment and extract its delivery snapshot."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import stripe

from server.schemas.base import quantize_money


class OrderPaymentMismatch(ValueError):
    """The linked payment is not a successful payment for this order."""


def fetch_payment_intent(payment_intent_id: str, *, client: stripe.StripeClient) -> dict[str, Any]:
    """Retrieve using this shop's client, independent of process-global credentials.

    The caller must release its database connection before this network call.
    Stripe errors propagate so completion can be retried without changing the order.
    """
    intent = client.payment_intents.retrieve(payment_intent_id)
    return intent.to_dict_recursive() if hasattr(intent, "to_dict_recursive") else dict(intent)


def verified_shipping_address(
    payment: Mapping[str, Any],
    *,
    payment_intent_id: str,
    customer_id: str,
    total: Decimal,
    requires_shipping: bool,
) -> dict[str, Any] | None:
    """Validate payment ownership/status/amount and copy shipping, never billing details.

    No I/O or state changes: the order endpoint commits this snapshot alongside its
    completion and stock changes. Non-shipping purchases may have no shipping data.
    """
    customer = payment.get("customer")
    if isinstance(customer, Mapping):
        customer = customer.get("id")
    if (
        payment.get("id") != payment_intent_id
        or payment.get("status") != "succeeded"
        or customer != customer_id
        or payment.get("currency") != "eur"
        or payment.get("amount_received") != int(quantize_money(total) * 100)
    ):
        raise OrderPaymentMismatch("The linked Stripe payment does not match this completed order")

    shipping = payment.get("shipping")
    if shipping is None and not requires_shipping:
        return None
    if not isinstance(shipping, Mapping) or not isinstance(shipping.get("address"), Mapping):
        raise OrderPaymentMismatch("The linked Stripe payment has no delivery address")
    address = shipping["address"]
    required = [shipping.get("name"), *(address.get(key) for key in ("line1", "postal_code", "city", "country"))]
    if not all(isinstance(value, str) and value.strip() for value in required):
        raise OrderPaymentMismatch("The linked Stripe payment has an incomplete delivery address")
    return {"name": shipping["name"], "phone": shipping.get("phone"), "address": dict(address)}
