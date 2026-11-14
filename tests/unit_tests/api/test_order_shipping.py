"""Checkout-to-email regressions: real persistence/rendering, mocked Stripe and delivery."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import stripe

from server import mail
from server.db import db
from server.db.models import Account, OrderTable, ProductTable, ShopTable
from server.settings import mail_settings
from tests.unit_tests.factories.account import make_account_with_stripe
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.order import make_shipping_address
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop_with_shipping

SHIPPING = make_shipping_address()


@pytest.fixture()
def checkout(test_client, monkeypatch):
    shop_id = make_shop_with_shipping(enabled=False)
    shop = db.session.get(ShopTable, shop_id)
    shop.stripe_secret_key = "sk_test_offline"
    shop.config = {**shop.config, "languages": {"main": {"language_name": "Nederlands"}}}
    account_id = make_account_with_stripe(shop_id, name="customer@example.com")
    category = make_category(shop_id=shop_id)
    product_id = make_product(shop_id=shop_id, category_id=category, stock=5)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=42,
        order_info=[{"product_id": str(product_id), "product_name": "Widget", "quantity": 1, "price": 12.10}],
        total=Decimal("12.10"),
        status="pending",
    )
    db.session.add(order)
    db.session.commit()
    order_id = order.id
    payment = {
        "id": "pi_offline",
        "client_secret": "pi_offline_secret",
        "status": "succeeded",
        "customer": "cus_test_123",
        "amount_received": 1210,
        "currency": "eur",
        "shipping": deepcopy(SHIPPING),
    }
    create = MagicMock(return_value=deepcopy(payment))
    retrieve = MagicMock(side_effect=lambda *args, **kwargs: deepcopy(payment))
    monkeypatch.setattr(stripe.PaymentIntent, "create", create)
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", retrieve)
    monkeypatch.setattr(mail_settings, "SHOP_MAIL_ENABLED", True)
    sent = []
    monkeypatch.setattr(mail, "send_mail", lambda message: sent.append(message))

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order_id}")
    assert response.status_code == 201, response.json()
    return {
        "order_id": order_id,
        "shop_id": shop_id,
        "account_id": account_id,
        "product_id": product_id,
        "payment": payment,
        "retrieve": retrieve,
        "create": create,
        "sent": sent,
    }


def test_checkout_shipping_populates_both_confirmation_emails(checkout, test_client):
    response = test_client.patch(f"/orders/{checkout['order_id']}", json={"status": "complete"})
    assert response.status_code == 201, response.json()
    assert len(checkout["sent"]) == 2
    for message in checkout["sent"]:
        for expected in ("Alex Example", "Example street 1", "Unit 2", "1234 AB", "Amsterdam", "NL"):
            assert expected in message["message"], f"{expected!r} missing from {message['subject']}"
    db.session.expire_all()
    order = db.session.get(OrderTable, checkout["order_id"])
    assert order.stripe_payment_intent_id == "pi_offline"
    assert order.shipping_address == SHIPPING
    assert db.session.get(Account, checkout["account_id"]).details == {"stripe_customer_id": "cus_test_123"}
    public_order = test_client.get(f"/orders/{checkout['order_id']}").json()
    assert "shipping_address" not in public_order
    assert "stripe_payment_intent_id" not in public_order


def test_order_address_survives_account_changes_and_repeat_completion(checkout, test_client):
    url = f"/orders/{checkout['order_id']}"
    assert test_client.patch(url, json={"status": "complete"}).status_code == 201
    account = db.session.get(Account, checkout["account_id"])
    account.details = {**account.details, "name": "Other Person", "address": "Other street 99", "city": "Other City"}
    db.session.commit()
    # A duplicate redirect must not re-fetch Stripe, send more mail or replace the snapshot.
    checkout["payment"]["shipping"]["name"] = "Changed in Stripe"
    checkout["retrieve"].reset_mock()
    assert test_client.patch(url, json={"status": "complete"}).status_code == 201
    checkout["retrieve"].assert_not_called()
    assert len(checkout["sent"]) == 2
    order = db.session.get(OrderTable, checkout["order_id"])
    for message, _, _ in mail.build_order_confirmation_mails(order, order.shop, account):
        assert "Alex Example" in message["message"]
        assert "Example street 1" in message["message"]
        assert "Other Person" not in message["message"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "processing"),
        ("id", "pi_other"),
        ("customer", "cus_other"),
        ("amount_received", 1209),
        ("currency", "usd"),
        ("shipping", None),
    ],
)
def test_invalid_payment_does_not_complete_or_send_mail(checkout, test_client, field, value):
    checkout["payment"][field] = value
    response = test_client.patch(f"/orders/{checkout['order_id']}", json={"status": "complete"})
    assert response.status_code == 409, response.json()
    db.session.expire_all()
    order = db.session.get(OrderTable, checkout["order_id"])
    assert order.status == "pending"
    assert order.completed_at is None
    assert order.shipping_address is None
    assert db.session.get(ProductTable, checkout["product_id"]).stock == 5
    assert checkout["sent"] == []


def test_stripe_outage_can_be_retried_without_losing_the_order(checkout, test_client):
    url = f"/orders/{checkout['order_id']}"
    checkout["retrieve"].side_effect = stripe.error.APIConnectionError("Offline")
    assert test_client.patch(url, json={"status": "complete"}).status_code == 502
    assert checkout["sent"] == []
    db.session.expire_all()
    assert db.session.get(OrderTable, checkout["order_id"]).status == "pending"
    checkout["retrieve"].side_effect = lambda *args, **kwargs: deepcopy(checkout["payment"])
    assert test_client.patch(url, json={"status": "complete"}).status_code == 201
    assert len(checkout["sent"]) == 2


def test_digital_payment_does_not_require_a_shipping_address(checkout, test_client):
    product = db.session.get(ProductTable, checkout["product_id"])
    product.shippable = False
    db.session.commit()
    checkout["payment"]["shipping"] = None
    response = test_client.patch(f"/orders/{checkout['order_id']}", json={"status": "complete"})
    assert response.status_code == 201, response.json()
    assert len(checkout["sent"]) == 2


def test_cancel_does_not_contact_stripe(checkout, test_client):
    response = test_client.patch(f"/orders/{checkout['order_id']}", json={"status": "cancelled"})
    assert response.status_code == 201, response.json()
    checkout["retrieve"].assert_not_called()
    assert checkout["sent"] == []
