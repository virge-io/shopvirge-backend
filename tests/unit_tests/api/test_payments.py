"""Tests for the provider-agnostic payments API.

The Mollie SDK is faked at the ``MollieProvider._get_client`` seam with
objects built from the real ``mollie.api.objects.payment.Payment`` class, so
the provider code is exercised against the SDK's actual object shape. Stripe
is faked at the PaymentIntent level.
"""

from uuid import uuid4

import pytest
from mollie.api.objects.payment import Payment as MolliePayment

from server.db import db
from server.db.models import PaymentTable, ShopTable
from server.payments.mollie import MollieProvider
from tests.unit_tests.factories.account import make_account
from tests.unit_tests.factories.order import make_pending_order
from tests.unit_tests.factories.shop import make_shop

CHECKOUT_URL = "https://www.mollie.com/checkout/select-method/test123"


class FakeMolliePayments:
    """Stand-in for ``client.payments`` backed by an in-memory dict."""

    def __init__(self):
        self.store = {}
        self.created_payloads = []
        self.counter = 0

    def create(self, payload):
        self.counter += 1
        self.created_payloads.append(payload)
        payment_id = f"tr_test{self.counter}"
        data = {
            "resource": "payment",
            "id": payment_id,
            "mode": "test",
            "status": "open",
            "amount": payload["amount"],
            "description": payload["description"],
            "metadata": payload.get("metadata"),
            "redirectUrl": payload.get("redirectUrl"),
            "webhookUrl": payload.get("webhookUrl"),
            "_links": {"checkout": {"href": CHECKOUT_URL}},
        }
        self.store[payment_id] = data
        return MolliePayment(data, None)

    def get(self, payment_id):
        return MolliePayment(self.store[payment_id], None)

    def set_status(self, payment_id, status):
        self.store[payment_id]["status"] = status


class FakeMollieClient:
    def __init__(self):
        self.payments = FakeMolliePayments()


@pytest.fixture()
def fake_mollie(monkeypatch):
    client = FakeMollieClient()
    monkeypatch.setattr(MollieProvider, "_get_client", lambda self, shop: client)
    return client


@pytest.fixture()
def mollie_shop():
    shop_id = make_shop(with_config=False, random_shop_name=True)
    shop = db.session.get(ShopTable, shop_id)
    shop.payment_provider = "mollie"
    shop.payment_config = {"mollie": {"api_key": "test_dummy_key"}}
    db.session.commit()
    return shop_id


@pytest.fixture()
def mollie_order(mollie_shop):
    account_id = make_account(shop_id=mollie_shop, name="payments@test.local")
    order = make_pending_order(
        shop_id=mollie_shop,
        account_id=account_id,
        product_id_1=uuid4(),
        product_id_2=uuid4(),
        total=2.0,
    )
    return {"shop_id": mollie_shop, "order_id": order.id}


def create_payment(test_client, shop_id, order_id, return_url="https://shop.test/checkout/return"):
    return test_client.post(
        f"/shops/{shop_id}/payments/",
        json={"order_id": str(order_id), "return_url": return_url},
    )


def test_create_mollie_payment_returns_redirect_session(test_client, fake_mollie, mollie_order):
    response = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"])
    assert response.status_code == 201, response.text
    session = response.json()

    assert session["provider"] == "mollie"
    assert session["flow"] == "redirect"
    assert session["redirect_url"] == CHECKOUT_URL
    assert session["status"] == "pending"
    assert session["client_secret"] is None
    assert float(session["amount"]) == 2.0

    # The amount is derived server-side from the order, never client input.
    payload = fake_mollie.payments.created_payloads[0]
    assert payload["amount"] == {"currency": "EUR", "value": "2.00"}
    assert payload["redirectUrl"] == "https://shop.test/checkout/return"
    # PUBLIC_BASE_URL is localhost in tests, so no webhookUrl is sent to Mollie.
    assert "webhookUrl" not in payload

    payment = db.session.get(PaymentTable, session["payment_id"])
    assert payment.provider_payment_id == "tr_test1"
    assert payment.status == "pending"
    assert str(payment.order_id) == str(mollie_order["order_id"])


def test_create_mollie_payment_includes_webhook_url_when_public(test_client, fake_mollie, mollie_order, monkeypatch):
    from server.settings import app_settings

    monkeypatch.setattr(app_settings, "PUBLIC_BASE_URL", "https://api.shopvirge.com")
    response = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"])
    assert response.status_code == 201, response.text

    payload = fake_mollie.payments.created_payloads[0]
    assert payload["webhookUrl"] == f"https://api.shopvirge.com/webhooks/payments/mollie/{mollie_order['shop_id']}"


def test_mollie_webhook_paid_completes_order(test_client, fake_mollie, mollie_order):
    session = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"]).json()

    fake_mollie.payments.set_status("tr_test1", "paid")
    response = test_client.post(
        f"/webhooks/payments/mollie/{mollie_order['shop_id']}",
        data={"id": "tr_test1"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}

    payment = db.session.get(PaymentTable, session["payment_id"])
    assert payment.status == "paid"

    order = test_client.get(f"/orders/{mollie_order['order_id']}").json()
    assert order["status"] == "complete"
    assert order["completed_at"] is not None

    # Mollie retries webhooks: a replay must be a harmless no-op.
    completed_at = order["completed_at"]
    response = test_client.post(
        f"/webhooks/payments/mollie/{mollie_order['shop_id']}",
        data={"id": "tr_test1"},
    )
    assert response.status_code == 200
    order = test_client.get(f"/orders/{mollie_order['order_id']}").json()
    assert order["status"] == "complete"
    assert order["completed_at"] == completed_at


def test_mollie_webhook_failed_keeps_order_pending(test_client, fake_mollie, mollie_order):
    session = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"]).json()

    fake_mollie.payments.set_status("tr_test1", "failed")
    response = test_client.post(
        f"/webhooks/payments/mollie/{mollie_order['shop_id']}",
        data={"id": "tr_test1"},
    )
    assert response.status_code == 200

    payment = db.session.get(PaymentTable, session["payment_id"])
    assert payment.status == "failed"
    order = test_client.get(f"/orders/{mollie_order['order_id']}").json()
    assert order["status"] == "pending"

    # A failed attempt does not block a retry: a fresh payment can be created.
    retry = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"])
    assert retry.status_code == 201
    assert retry.json()["payment_id"] != session["payment_id"]


def test_get_payment_syncs_status_from_provider(test_client, fake_mollie, mollie_order):
    """Poll-time sync is the webhook fallback (e.g. local dev, missed webhook)."""
    session = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"]).json()

    fake_mollie.payments.set_status("tr_test1", "paid")
    response = test_client.get(f"/shops/{mollie_order['shop_id']}/payments/{session['payment_id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "paid"
    assert body["order_status"] == "complete"


def test_mollie_webhook_without_id_is_rejected(test_client, fake_mollie, mollie_order):
    response = test_client.post(f"/webhooks/payments/mollie/{mollie_order['shop_id']}", data={})
    assert response.status_code == 400


def test_webhook_unknown_payment_returns_404(test_client, fake_mollie, mollie_order):
    fake_mollie.payments.store["tr_unknown"] = {
        "resource": "payment",
        "id": "tr_unknown",
        "status": "paid",
        "_links": {},
    }
    response = test_client.post(
        f"/webhooks/payments/mollie/{mollie_order['shop_id']}",
        data={"id": "tr_unknown"},
    )
    assert response.status_code == 404


def test_webhook_unknown_provider_returns_404(test_client, mollie_order):
    response = test_client.post(
        f"/webhooks/payments/adyen/{mollie_order['shop_id']}",
        data={"id": "tr_test1"},
    )
    assert response.status_code == 404


def test_create_payment_for_completed_order_conflicts(test_client, fake_mollie, mollie_order):
    from server.db.models import OrderTable

    order = db.session.get(OrderTable, mollie_order["order_id"])
    order.status = "complete"
    db.session.commit()

    response = create_payment(test_client, mollie_order["shop_id"], mollie_order["order_id"])
    assert response.status_code == 409


def test_create_payment_unconfigured_stripe_shop_is_400(test_client):
    """Default provider is stripe; a shop without a secret key gets a clean 400."""
    shop_id = make_shop(with_config=False, random_shop_name=True)
    account_id = make_account(shop_id=shop_id, name="stripe@test.local")
    order = make_pending_order(shop_id=shop_id, account_id=account_id, product_id_1=uuid4(), product_id_2=uuid4())
    response = create_payment(test_client, shop_id, order.id)
    assert response.status_code == 400


def test_create_stripe_payment_returns_client_confirmation_session(test_client, monkeypatch):
    shop_id = make_shop(with_config=False, random_shop_name=True)
    shop = db.session.get(ShopTable, shop_id)
    shop.stripe_secret_key = "sk_test_dummy"
    shop.stripe_public_key = "pk_test_dummy"
    db.session.commit()

    account_id = make_account(shop_id=shop_id, name="stripe@test.local")
    order = make_pending_order(
        shop_id=shop_id, account_id=account_id, product_id_1=uuid4(), product_id_2=uuid4(), total=2.0
    )

    created_kwargs = {}

    def fake_intent_create(**kwargs):
        created_kwargs.update(kwargs)
        return {"id": "pi_test1", "status": "requires_payment_method", "client_secret": "pi_test1_secret"}

    import stripe as stripe_sdk

    monkeypatch.setattr(stripe_sdk.PaymentIntent, "create", staticmethod(fake_intent_create))

    response = create_payment(test_client, shop_id, order.id)
    assert response.status_code == 201, response.text
    session = response.json()

    assert session["provider"] == "stripe"
    assert session["flow"] == "client_confirmation"
    assert session["client_secret"] == "pi_test1_secret"
    assert session["publishable_key"] == "pk_test_dummy"
    assert session["redirect_url"] is None

    # Amount in cents, derived from the order total — not client input.
    assert created_kwargs["amount"] == 200
    assert created_kwargs["currency"] == "eur"
    # Guest checkout: no stripe customer on the account, so no customer passed.
    assert "customer" not in created_kwargs
