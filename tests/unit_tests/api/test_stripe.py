from decimal import Decimal
from types import SimpleNamespace

from server.api.endpoints.shop_endpoints import stripe as stripe_endpoint
from server.db import db
from server.db.models import OrderTable
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
