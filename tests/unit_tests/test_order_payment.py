from copy import deepcopy
from decimal import Decimal

import pytest
import stripe

from server.services.order_payment import OrderPaymentMismatch, fetch_payment_intent, verified_shipping_address


@pytest.fixture()
def payment():
    return {
        "id": "pi_order",
        "status": "succeeded",
        "customer": "cus_order",
        "currency": "eur",
        "amount_received": 1234,
        "shipping": {
            "name": "Alex Example",
            "phone": None,
            "address": {"line1": "Example 1", "postal_code": "1234 AB", "city": "Amsterdam", "country": "NL"},
        },
    }


def verify(payment, requires_shipping=True):
    return verified_shipping_address(
        payment,
        payment_intent_id="pi_order",
        customer_id="cus_order",
        total=Decimal("12.34"),
        requires_shipping=requires_shipping,
    )


def test_sdk_payment_object_is_fetched_with_the_explicit_shop_key(payment, monkeypatch):
    captured = {}
    sdk_payment = stripe.PaymentIntent.construct_from(payment, "sk_test_offline")

    def retrieve(intent_id, **kwargs):
        captured.update(intent_id=intent_id, **kwargs)
        return sdk_payment

    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", retrieve)
    result = fetch_payment_intent("pi_order", api_key="sk_test_shop")
    assert captured == {"intent_id": "pi_order", "api_key": "sk_test_shop"}
    assert result == payment
    assert verify(result) == payment["shipping"]


def test_expanded_customer_is_supported(payment):
    payment["customer"] = {"id": "cus_order", "object": "customer"}
    assert verify(payment) == payment["shipping"]


@pytest.mark.parametrize("field", ["name", "line1", "postal_code", "city", "country"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_incomplete_shipping_is_rejected(payment, field, value):
    target = payment["shipping"] if field == "name" else payment["shipping"]["address"]
    target[field] = value
    with pytest.raises(OrderPaymentMismatch, match="incomplete"):
        verify(payment)


def test_billing_address_does_not_replace_a_missing_delivery_address(payment):
    payment["payment_method"] = {"billing_details": deepcopy(payment["shipping"])}
    payment["shipping"] = None
    with pytest.raises(OrderPaymentMismatch, match="no delivery address"):
        verify(payment)


def test_snapshot_is_independent_of_the_stripe_payload(payment):
    snapshot = verify(payment)
    payment["shipping"]["address"]["line1"] = "Changed later"
    assert snapshot["address"]["line1"] == "Example 1"


def test_digital_payment_can_omit_shipping(payment):
    payment["shipping"] = None
    assert verify(payment, requires_shipping=False) is None
