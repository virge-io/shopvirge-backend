import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import stripe
from structlog.testing import capture_logs

from server.api.endpoints.checkout import stripe as stripe_endpoint
from server.db import db
from server.db.models import Account, OrderTable, ShopTable
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
    monkeypatch.setattr(stripe_client, "get_api_key", lambda shop: "sk_test_resolved")
    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "create",
        lambda self, params, options=None: (
            captured.update(params | (options or {})) or {"id": "pi_test", "client_secret": "secret"}
        ),
    )

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}")

    assert response.status_code == 201, response.json()
    assert response.json() == {"clientSecret": "secret"}
    assert captured["amount"] == 1234
    assert captured["customer"] == "cus_test_123"
    assert captured["metadata"] == {"order_id": str(order.id), "shop_id": str(shop_id)}
    db.session.expire_all()
    assert db.session.get(OrderTable, order.id).stripe_payment_intent_id == "pi_test"


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
    monkeypatch.setattr(stripe_client, "get_api_key", lambda shop: "sk_test_resolved")
    customer_create = {}
    monkeypatch.setattr(
        stripe_endpoint.stripe.CustomerService,
        "create",
        lambda self, params, options=None: (
            customer_create.update(params | (options or {})) or SimpleNamespace(id="cus_replacement")
        ),
    )

    def create_intent(**kwargs):
        intents.append(kwargs)
        if kwargs["customer"] == "cus_stale":
            raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")
        return {"id": "pi_replacement", "client_secret": "secret"}

    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "create",
        lambda self, params, options=None: create_intent(**params, **(options or {})),
    )

    response = test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}")

    assert response.status_code == 201, response.json()
    assert [intent["customer"] for intent in intents] == ["cus_stale", "cus_replacement"]
    assert customer_create["email"] == "Test Account"
    assert customer_create["idempotency_key"].startswith("replace-customer-")
    db.session.expire_all()
    assert db.session.get(Account, account_id).details["stripe_customer_id"] == "cus_replacement"
    assert db.session.get(OrderTable, order.id).stripe_payment_intent_id == "pi_replacement"


def test_subscription_replaces_a_customer_missing_from_the_shop_stripe_account(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id, customer_id="cus_stale")
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=1,
        order_info=[{"product_id": "product-1", "quantity": 1, "plan": "monthly"}],
        total=Decimal("12.34"),
    )
    db.session.add(order)
    db.session.commit()

    subscriptions = []
    monkeypatch.setattr(stripe_client, "get_api_key", lambda shop: "sk_test_resolved")
    monkeypatch.setattr(
        stripe_endpoint.stripe.CustomerService,
        "create",
        lambda self, params, options=None: SimpleNamespace(id="cus_replacement"),
    )
    monkeypatch.setattr(
        stripe_endpoint.stripe.PriceService,
        "list",
        lambda self, params, options=None: SimpleNamespace(
            data=[SimpleNamespace(lookup_key="monthly-product-1", id="price_1")]
        ),
    )

    def create_subscription(**kwargs):
        subscriptions.append(kwargs)
        if kwargs["customer"] == "cus_stale":
            raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")
        return SimpleNamespace(
            id="sub_replacement",
            latest_invoice=SimpleNamespace(
                payment_intent=SimpleNamespace(id="pi_subscription", client_secret="secret")
            ),
        )

    monkeypatch.setattr(
        stripe_endpoint.stripe.SubscriptionService,
        "create",
        lambda self, params, options=None: create_subscription(**params, **(options or {})),
    )

    response = test_client.post(f"/shops/{shop_id}/stripe/subscription?order_id={order.id}")

    assert response.status_code == 201, response.json()
    assert [subscription["customer"] for subscription in subscriptions] == ["cus_stale", "cus_replacement"]
    db.session.expire_all()
    assert db.session.get(Account, account_id).details["stripe_customer_id"] == "cus_replacement"
    assert db.session.get(OrderTable, order.id).stripe_payment_intent_id == "pi_subscription"


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
        stripe_endpoint.stripe.PriceService,
        "list",
        lambda self, params, options=None: SimpleNamespace(
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
        client=stripe_client.get_client(SimpleNamespace(stripe_secret_key="sk_test_offline")),
    )

    assert items == [{"price": "price_1", "quantity": 3}, {"price": "price_2", "quantity": 2}]


def test_repeated_checkout_reuses_the_linked_payment(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id)
    order = OrderTable(shop_id=shop_id, account_id=account_id, total=Decimal("12.34"), order_info=[])
    db.session.add(order)
    db.session.commit()
    order_id = order.id
    requests = []
    retrieve = MagicMock(return_value={"id": "pi_same", "client_secret": "secret"})
    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "retrieve",
        lambda self, resource_id, params=None, options=None: retrieve(resource_id, **(params or {})),
    )
    monkeypatch.setattr(stripe_client, "get_api_key", lambda shop: "sk_test_resolved")
    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "create",
        lambda self, params, options=None: (
            requests.append(params | (options or {})) or {"id": "pi_same", "client_secret": "secret"}
        ),
    )
    url = f"/shops/{shop_id}/stripe/?order_id={order_id}"
    assert test_client.post(url).status_code == 201
    with capture_logs() as logs:
        assert test_client.post(url).status_code == 201
    entry = next(log for log in logs if log["event"] == "Resumed checkout with linked payment intent")
    assert entry == {
        "event": "Resumed checkout with linked payment intent",
        "log_level": "info",
        "order_id": str(order_id),
        "shop_id": str(shop_id),
        "payment_intent_id": "pi_same",
        "subscription_id": None,
    }
    assert len(requests) == 1
    assert requests[0]["idempotency_key"] == f"order-{order_id}-cus_test_123"
    retrieve.assert_called_once_with("pi_same")


def test_repeated_subscription_checkout_reuses_its_initial_payment(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        total=Decimal("12.34"),
        order_info=[{"plan": "monthly"}],
        stripe_payment_intent_id="pi_existing_subscription",
    )
    db.session.add(order)
    db.session.commit()
    monkeypatch.setattr(stripe_client, "get_api_key", lambda shop: "sk_test_resolved")
    retrieve = MagicMock(
        return_value={
            "client_secret": "existing_secret",
            "invoice": {"subscription": {"id": "sub_existing"}},
        }
    )
    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "retrieve",
        lambda self, resource_id, params=None, options=None: retrieve(resource_id, **(params or {})),
    )
    create = MagicMock(side_effect=AssertionError("Must reuse the subscription"))
    monkeypatch.setattr(
        stripe_endpoint.stripe.SubscriptionService,
        "create",
        lambda self, params, options=None: create(**params, **(options or {})),
    )
    response = test_client.post(f"/shops/{shop_id}/stripe/subscription?order_id={order.id}")
    assert response.status_code == 201, response.json()
    assert response.json() == {"clientSecret": "existing_secret", "subscriptionId": "sub_existing"}
    create.assert_not_called()
    retrieve.assert_called_once_with("pi_existing_subscription", expand=["invoice.subscription"])


def test_completed_order_cannot_replace_its_payment(test_client, monkeypatch):
    shop_id = make_shop()
    account_id = make_account_with_stripe(shop_id)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        total=Decimal("12.34"),
        order_info=[],
        status="complete",
        stripe_payment_intent_id="pi_original",
    )
    db.session.add(order)
    db.session.commit()

    def unexpected_call(**kwargs):
        raise AssertionError("Completed orders must not contact Stripe")

    monkeypatch.setattr(
        stripe_endpoint.stripe.PaymentIntentService,
        "create",
        lambda self, params, options=None: unexpected_call(**params, **(options or {})),
    )
    assert test_client.post(f"/shops/{shop_id}/stripe/?order_id={order.id}").status_code == 409
    assert order.stripe_payment_intent_id == "pi_original"


def test_subscription_cancellation_uses_shop_client_without_a_database_connection(test_client, monkeypatch, real_db):
    shop_id = make_shop()
    real_db.append(shop_id)
    shop = db.session.get(ShopTable, shop_id)
    shop.stripe_secret_key = "sk_test_cancel"
    db.session.commit()
    monkeypatch.setattr(stripe, "api_key", "sk_test_other_shop")
    requests = []

    def request(self, method, url, headers, post_data=None):
        assert not db.session.in_transaction()
        requests.append((method, url, headers["Authorization"]))
        return json.dumps({"id": "sub_cancelled", "object": "subscription", "status": "canceled"}), 200, {}

    monkeypatch.setattr(stripe.RequestsClient, "request", request)
    response = test_client.delete(f"/shops/{shop_id}/stripe/subscription/sub_cancelled")
    assert response.status_code == 204, response.text
    assert requests == [("delete", "https://api.stripe.com/v1/subscriptions/sub_cancelled", "Bearer sk_test_cancel")]
    assert stripe.api_key == "sk_test_other_shop"
