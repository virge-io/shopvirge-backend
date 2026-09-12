from decimal import Decimal
from types import SimpleNamespace

import stripe

from server.api.endpoints.shop_endpoints import stripe as stripe_endpoint
from server.db import db
from server.db.models import Account, OrderTable
from server.services import stripe_client
from tests.unit_tests.factories.account import make_account_with_stripe
from tests.unit_tests.factories.shop import make_shop


def test_payment_intent_uses_persisted_order_total(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=1,
        order_info=[],
        total=Decimal("12.34"),
    )
    db.session.add(order)
    db.session.commit()

    captured = {}
    monkeypatch.setattr(stripe_client, "configure_for_shop", lambda shop: None)
    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntent,
        "create",
        lambda **kwargs: captured.update(kwargs) or {"client_secret": "secret"},
    )

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}")

    assert response.status_code == 201, response.json()
    assert response.json() == {"clientSecret": "secret"}
    assert captured["amount"] == 1234
    assert captured["customer"] == "cus_test_123"


def test_payment_intent_replaces_a_customer_missing_from_the_shop_stripe_account(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id, customer_id="cus_stale")
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=1,
        order_info=[],
        total=Decimal("12.34"),
    )
    db.session.add(order)
    db.session.commit()

    intents = []
    monkeypatch.setattr(stripe_client, "configure_for_shop", lambda shop: None)
    customer_create = {}
    monkeypatch.setattr(
        stripe_endpoint.stripe.Customer,
        "create",
        lambda **kwargs: customer_create.update(kwargs) or SimpleNamespace(id="cus_replacement"),
    )

    def create_intent(**kwargs):
        intents.append(kwargs)
        if kwargs["customer"] == "cus_stale":
            raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")
        return {"client_secret": "secret"}

    monkeypatch.setattr(stripe_endpoint.stripe.PaymentIntent, "create", create_intent)

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}")

    assert response.status_code == 201, response.json()
    assert [intent["customer"] for intent in intents] == ["cus_stale", "cus_replacement"]
    assert customer_create == {"email": "Test Account"}
    db.session.expire_all()
    assert db.session.get(Account, account_id).details["stripe_customer_id"] == "cus_replacement"


def test_payment_intent_rejects_recurring_orders(test_client):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=1,
        order_info=[{"plan": "monthly"}],
        total=Decimal("12.34"),
    )
    db.session.add(order)
    db.session.commit()

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}")

    assert response.status_code == 422, response.json()


def test_subscription_items_keep_ordered_quantities(monkeypatch):
    monkeypatch.setattr(
        stripe_endpoint.stripe.Price,
        "list",
        lambda **_: SimpleNamespace(
            data=[
                SimpleNamespace(lookup_key="monthly-product-1", id="price_1"),
                SimpleNamespace(lookup_key="monthly-product-2", id="price_2"),
            ]
        ),
    )

    items = stripe_endpoint.get_stripe_prices(
        [
            {"product_id": "product-1", "quantity": 3},
            {"product_id": "product-2", "quantity": 2},
        ],
        yearly=False,
    )

    assert items == [{"price": "price_1", "quantity": 3}, {"price": "price_2", "quantity": 2}]
