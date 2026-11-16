"""Issue #385: real concurrent persistence, offline Stripe and notification delivery."""

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe
from sqlalchemy import text

from server import mail
from server.db import db
from server.db.models import Account, OrderTable, ProductTable, ShopTable
from server.settings import mail_settings
from tests.unit_tests.factories.account import make_account_with_stripe
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.order import make_shipping_address
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop_with_shipping


@pytest.fixture()
def replacement_checkout(real_db, monkeypatch):
    shop_id = make_shop_with_shipping(enabled=False)
    real_db.append(shop_id)
    shop = db.session.get(ShopTable, shop_id)
    shop.stripe_secret_key = "sk_test_385"
    shop.config = {
        **shop.config,
        "languages": {"main": {"language_name": "Nederlands"}},
        "toggles": {**shop.config["toggles"], "enable_stock_on_products": True},
    }
    account_id = make_account_with_stripe(shop_id, name="buyer@example.com", customer_id="cus_stale")
    product_id = make_product(shop_id=shop_id, category_id=make_category(shop_id=shop_id), stock=5)
    order = OrderTable(
        shop_id=shop_id,
        account_id=account_id,
        customer_order_id=1,
        total=Decimal("12.10"),
        order_info=[{"product_id": str(product_id), "product_name": "Widget", "quantity": 1, "price": 12.10}],
    )
    db.session.add(order)
    db.session.commit()
    sent = []
    monkeypatch.setattr(mail_settings, "SHOP_MAIL_ENABLED", True)
    monkeypatch.setattr(mail, "send_mail", lambda message: sent.append(message))
    return {"shop": shop_id, "account": account_id, "product": product_id, "order": order.id, "sent": sent}


@pytest.mark.parametrize("plan", [None, "monthly", "yearly"])
@pytest.mark.parametrize("separate_orders", [False, True])
def test_overlapping_missing_customer_requests_share_payment_and_complete(
    replacement_checkout, test_client, monkeypatch, separate_orders, plan
):
    ids = replacement_checkout
    if plan:
        order = db.session.get(OrderTable, ids["order"])
        order.order_info = [{**line, "plan": plan} for line in order.order_info]
        db.session.commit()
    order_ids = [ids["order"]] * 4
    if separate_orders:
        original = db.session.get(OrderTable, ids["order"])
        second = OrderTable(
            shop_id=ids["shop"],
            account_id=ids["account"],
            customer_order_id=2,
            total=original.total,
            order_info=deepcopy(original.order_info),
        )
        db.session.add(second)
        db.session.commit()
        order_ids[2:] = [second.id] * 2
    stale_calls = threading.Barrier(4)
    replacements = threading.Barrier(4)
    lock = threading.Lock()
    customers, payments, remote_transactions, keys = {}, {}, [], []

    def create_customer(**kwargs):
        with lock:
            remote_transactions.append(db.session.in_transaction())
            keys.append(kwargs.get("api_key"))
            # Faithful idempotency: no key creates a distinct remote customer.
            key = kwargs.get("idempotency_key") or str(threading.get_ident())
            customer = customers.setdefault(key, f"cus_new_{len(customers)}")
        replacements.wait(timeout=10)
        return SimpleNamespace(id=customer)

    def create_payment(**kwargs):
        if kwargs["customer"] == "cus_stale":
            stale_calls.wait(timeout=10)
            raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")
        with lock:
            keys.append(kwargs.get("api_key"))
            remote_transactions.append(db.session.in_transaction())
            return deepcopy(
                payments.setdefault(
                    kwargs["idempotency_key"],
                    {
                        "id": f"pi_{kwargs['metadata']['order_id']}",
                        "client_secret": f"secret_{kwargs['metadata']['order_id']}",
                        "customer": kwargs["customer"],
                        "status": "succeeded",
                        "currency": "eur",
                        "amount_received": 1210,
                        "shipping": make_shipping_address(),
                    },
                )
            )

    monkeypatch.setattr(stripe.Customer, "create", create_customer)
    monkeypatch.setattr(stripe.PaymentIntent, "create", create_payment)

    def list_prices(**kwargs):
        assert kwargs["api_key"] == "sk_test_385"
        assert not db.session.in_transaction()
        return SimpleNamespace(
            data=[SimpleNamespace(lookup_key=key, id=f"price_{key}") for key in kwargs["lookup_keys"]]
        )

    def create_subscription(**kwargs):
        payment = create_payment(**kwargs)
        return SimpleNamespace(
            id=f"sub_{payment['id']}",
            latest_invoice=SimpleNamespace(
                payment_intent=SimpleNamespace(id=payment["id"], client_secret=payment["client_secret"])
            ),
        )

    monkeypatch.setattr(stripe.Price, "list", list_prices)
    monkeypatch.setattr(stripe.Subscription, "create", create_subscription)
    suffix = "subscription" if plan else ""

    monkeypatch.setattr(
        stripe.PaymentIntent,
        "retrieve",
        lambda intent_id, **k: deepcopy(next(p for p in payments.values() if p["id"] == intent_id)),
    )
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(
            workers.map(
                lambda order_id: test_client.post(f"/shops/{ids['shop']}/stripe/{suffix}?order_id={order_id}"),
                order_ids,
            )
        )
    assert [r.status_code for r in responses] == [201] * 4, [r.json() for r in responses]
    assert len(customers) == 1
    assert len(payments) == len({r.json()["clientSecret"] for r in responses}) == len(set(order_ids))
    assert not any(remote_transactions)
    assert set(keys) == {"sk_test_385"}
    db.session.expire_all()
    order = db.session.get(OrderTable, ids["order"])
    assert order.stripe_payment_customer_id == order.account.details["stripe_customer_id"]
    complete = f"/orders/{ids['order']}"
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: test_client.patch(complete, json={"status": "complete"}), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    db.session.expire_all()
    assert db.session.get(ProductTable, ids["product"]).stock == 4
    assert db.session.get(OrderTable, ids["order"]).shipping_address == make_shipping_address()
    assert len(ids["sent"]) == 2


def test_linked_payment_survives_later_account_customer_change(replacement_checkout, test_client, monkeypatch):
    ids = replacement_checkout
    payment = {
        "id": "pi_bound",
        "client_secret": "secret",
        "customer": "cus_stale",
        "status": "succeeded",
        "currency": "eur",
        "amount_received": 1210,
        "shipping": make_shipping_address(),
    }
    monkeypatch.setattr(stripe.PaymentIntent, "create", lambda **k: deepcopy(payment))
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", lambda *a, **k: deepcopy(payment))
    assert test_client.post(f"/shops/{ids['shop']}/stripe/?order_id={ids['order']}").status_code == 201
    account = db.session.get(Account, ids["account"])
    account.details = {"stripe_customer_id": "cus_later"}
    db.session.commit()
    response = test_client.patch(f"/orders/{ids['order']}", json={"status": "complete"})
    assert response.status_code == 201, response.json()


@pytest.mark.parametrize("winner", [None, "cus_other_worker"])
def test_replacement_refreshes_details_and_reuses_committed_winner(replacement_checkout, monkeypatch, winner):
    from server.api.endpoints.checkout.stripe import replace_missing_customer

    ids = replacement_checkout

    def create_customer(**kwargs):
        assert not db.session.in_transaction()
        with db.wrapped_database.engine.begin() as conn:
            conn.execute(
                text("UPDATE accounts SET details = CAST(:details AS jsonb) WHERE id = :id"),
                {
                    "id": str(ids["account"]),
                    "details": '{"note":"concurrent edit","stripe_customer_id":"' + (winner or "cus_stale") + '"}',
                },
            )
        return SimpleNamespace(id="cus_candidate")

    monkeypatch.setattr(stripe.Customer, "create", create_customer)
    result = replace_missing_customer(ids["account"], ids["shop"], "cus_stale", api_key="sk_test_385")
    assert result == (winner or "cus_candidate")
    db.session.expire_all()
    assert db.session.get(Account, ids["account"]).details == {
        "note": "concurrent edit",
        "stripe_customer_id": result,
    }
    # A delayed old request should skip remote customer creation altogether.
    monkeypatch.setattr(stripe.Customer, "create", lambda **k: pytest.fail("Must reuse the committed customer"))
    assert replace_missing_customer(ids["account"], ids["shop"], "cus_stale", api_key="sk_test_385") == result


@pytest.mark.parametrize("failure", ["remote", "commit"])
def test_failed_setup_does_not_persist_a_partial_payment_link(replacement_checkout, test_client, monkeypatch, failure):
    ids = replacement_checkout

    def create_payment(**kwargs):
        assert not db.session.in_transaction()
        if failure == "remote":
            raise stripe.error.APIConnectionError("Offline")
        # Fail the linkage commit, not fixture setup; middleware closes/rolls back the request session.
        monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("Commit failed")))
        return {"id": "pi_failed_commit", "client_secret": "secret"}

    monkeypatch.setattr(stripe.PaymentIntent, "create", create_payment)
    response = test_client.post(f"/shops/{ids['shop']}/stripe/?order_id={ids['order']}")
    assert response.status_code == 502
    db.session.expire_all()
    order = db.session.get(OrderTable, ids["order"])
    assert order.stripe_payment_intent_id is None
    assert order.stripe_payment_customer_id is None
    assert order.status == "pending"
    assert ids["sent"] == []


@pytest.mark.parametrize("snapshot", [None, "cus_expected"])
def test_customer_mismatches_remain_rejected_with_snapshot_and_legacy_orders(
    replacement_checkout, test_client, monkeypatch, snapshot
):
    ids = replacement_checkout
    order = db.session.get(OrderTable, ids["order"])
    order.stripe_payment_intent_id = "pi_mismatch"
    order.stripe_payment_customer_id = snapshot
    db.session.commit()
    monkeypatch.setattr(
        stripe.PaymentIntent,
        "retrieve",
        lambda *a, **k: {
            "id": "pi_mismatch",
            "customer": "cus_wrong",
            "status": "succeeded",
            "currency": "eur",
            "amount_received": 1210,
            "shipping": make_shipping_address(),
        },
    )
    assert test_client.patch(f"/orders/{ids['order']}", json={"status": "complete"}).status_code == 409
    db.session.expire_all()
    assert db.session.get(OrderTable, ids["order"]).status == "pending"
    assert db.session.get(ProductTable, ids["product"]).stock == 5
    assert ids["sent"] == []


def test_payment_customer_pair_cannot_be_overwritten(replacement_checkout):
    from fastapi import HTTPException

    from server.api.endpoints.checkout.stripe import _save_payment_intent

    ids = replacement_checkout
    _save_payment_intent(ids["order"], "pi_bound", "cus_bound")
    for payment_id, customer_id in [("pi_other", "cus_bound"), ("pi_bound", "cus_other")]:
        with pytest.raises(HTTPException) as exc:
            _save_payment_intent(ids["order"], payment_id, customer_id)
        assert exc.value.status_code == 409
        db.session.rollback()
    order = db.session.get(OrderTable, ids["order"])
    assert (order.stripe_payment_intent_id, order.stripe_payment_customer_id) == ("pi_bound", "cus_bound")


def test_replacement_retry_reuses_remote_idempotency_key(replacement_checkout, monkeypatch):
    from server.api.endpoints.checkout.stripe import replace_missing_customer

    ids = replacement_checkout
    calls = []

    def customer_create(**kwargs):
        assert not db.session.in_transaction()
        calls.append(kwargs)
        if len(calls) == 1:
            raise stripe.error.APIConnectionError("Response lost")
        return SimpleNamespace(id="cus_retried")

    monkeypatch.setattr(stripe.Customer, "create", customer_create)
    with pytest.raises(stripe.error.APIConnectionError):
        replace_missing_customer(ids["account"], ids["shop"], "cus_stale", api_key="sk_test_385")
    assert replace_missing_customer(ids["account"], ids["shop"], "cus_stale", api_key="sk_test_385") == "cus_retried"
    assert calls[0] == calls[1]


def test_explicit_shop_key_survives_process_global_key_change(replacement_checkout, test_client, monkeypatch):
    ids = replacement_checkout

    def create_payment(**kwargs):
        stripe.api_key = "sk_test_another_shop"
        assert kwargs["api_key"] == "sk_test_385"
        raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")

    def create_customer(**kwargs):
        assert kwargs["api_key"] == "sk_test_385"
        assert not db.session.in_transaction()
        return SimpleNamespace(id="cus_replaced")

    def retry_payment(**kwargs):
        if kwargs["customer"] == "cus_stale":
            return create_payment(**kwargs)
        assert kwargs["api_key"] == "sk_test_385"
        return {"id": "pi_correct_shop", "client_secret": "secret"}

    monkeypatch.setattr(stripe.PaymentIntent, "create", retry_payment)
    monkeypatch.setattr(stripe.Customer, "create", create_customer)
    assert test_client.post(f"/shops/{ids['shop']}/stripe/?order_id={ids['order']}").status_code == 201
