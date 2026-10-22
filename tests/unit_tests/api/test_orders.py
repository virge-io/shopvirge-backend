import threading
import time
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import scoped_session, sessionmaker

from server.api.endpoints.orders import public
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.database import SESSION_ARGUMENTS, BaseModel, SearchQuery
from server.db.models import OrderTable, ProductTable, ShopTable
from server.settings import mail_settings
from tests.unit_tests.factories.account import make_account
from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.order import make_pending_order
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop_with_shipping


def test_orders_get_multi(shop, pending_order, test_client):
    response = test_client.get("/orders/")
    assert response.status_code == 200
    orders = response.json()
    assert 1 == len(orders)
    assert 2 == len(orders[0]["order_info"])
    info_total = 0
    for order in orders:
        for info in order["order_info"]:
            info_total += info["price"] * info["quantity"]
        info_total += order.get("shipping_fee_inc_btw") or 0
        # Total matches info total
        assert order["total"] == info_total


# --- Read-only order tools exposed to MCP (list_pending_orders / list_complete_orders) ---


def test_list_pending_orders_endpoint(shop, pending_order, test_client):
    resp = test_client.get(f"/orders/shop/{shop}/pending")
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) == 1
    assert orders[0]["status"] == "pending"


def test_list_complete_orders_excludes_pending(shop, pending_order, test_client):
    """A pending order must not appear in the complete/cancelled history feed."""
    resp = test_client.get(f"/orders/shop/{shop}/complete")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pending_orders_filters_by_path_shop(shop, pending_order, test_client):
    """Results are filtered by the path shop_id: another shop's path returns no rows.

    NOTE: this only proves the query filter, not caller authorization. Whether a
    caller is *allowed* to read the shop in the path is covered by
    ``test_list_pending_orders_rejects_foreign_api_key`` below.
    """
    other_shop = uuid4()
    resp = test_client.get(f"/orders/shop/{other_shop}/pending")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pending_orders_opens_with_api_key(shop, pending_order, real_auth_client):
    """The read-only order tool is reachable with a per-shop API key."""
    _, plaintext = make_api_key(shop, name="orders-reader")
    resp = real_auth_client.get(f"/orders/shop/{shop}/pending", headers={"X-API-Key": plaintext})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


def test_list_pending_orders_rejects_foreign_api_key(shop, pending_order, real_auth_client):
    """An API key minted for shop A must NOT read shop B's orders (cross-tenant PII)."""
    other_shop = make_shop_with_shipping()
    _, plaintext = make_api_key(other_shop, name="foreign-reader")
    resp = real_auth_client.get(f"/orders/shop/{shop}/pending", headers={"X-API-Key": plaintext})
    assert resp.status_code == 403, resp.text


@pytest.fixture()
def shop_no_shipping_with_products():
    shop_id = make_shop_with_shipping(enabled=False)
    category = make_category(shop_id=shop_id)
    p1 = make_product(shop_id=shop_id, category_id=category, main_name="Item 1", price=10.0)
    p2 = make_product(shop_id=shop_id, category_id=category, main_name="Item 2", price=20.0)
    return {"shop_id": shop_id, "p1": p1, "p2": p2}


@pytest.fixture()
def shop_shipping_fixed_with_products():
    shop_id = make_shop_with_shipping(fixed_fee=4.95)
    category = make_category(shop_id=shop_id)
    p1 = make_product(shop_id=shop_id, category_id=category, main_name="Item 1", price=10.0)
    p2 = make_product(shop_id=shop_id, category_id=category, main_name="Item 2", price=20.0)
    return {"shop_id": shop_id, "p1": p1, "p2": p2}


@pytest.fixture()
def shop_shipping_mixed_vat():
    shop_id = make_shop_with_shipping(fixed_fee=10.0)
    category = make_category(shop_id=shop_id)
    p_high = make_product(
        shop_id=shop_id, category_id=category, main_name="Std VAT", price=100.0, tax_category="vat_standard"
    )
    p_low = make_product(
        shop_id=shop_id, category_id=category, main_name="Low VAT", price=100.0, tax_category="vat_lower_1"
    )
    return {"shop_id": shop_id, "p_high": p_high, "p_low": p_low}


@pytest.fixture()
def shop_shipping_free_above():
    shop_id = make_shop_with_shipping(
        fixed_fee=4.95,
        free_shipping_above_enabled=True,
        free_shipping_above_amount=50.0,
    )
    category = make_category(shop_id=shop_id)
    p1 = make_product(shop_id=shop_id, category_id=category, main_name="Item 1", price=10.0)
    return {"shop_id": shop_id, "p1": p1}


def _order_body(shop_id, items):
    return {
        "shop_id": str(shop_id),
        "order_info": items,
        "account_name": f"buyer-{shop_id}@example.com",
        "notes": "test",
    }


def test_create_order_no_shipping(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    items = [
        {"description": "x", "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
        {"description": "x", "product_id": str(ids["p2"]), "product_name": "Item 2", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    assert j["shipping_fee_inc_btw"] is None
    # Product prices are ex-VAT: (10 * 1.21 * 2) + (20 * 1.21) = 48.40.
    assert j["total"] == 48.4


def test_quote_order_calculates_gross_price_from_net_product_price(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    category = make_category(shop_id=ids["shop_id"])
    product_id = make_product(
        shop_id=ids["shop_id"],
        category_id=category,
        main_name="VAT example",
        price=100.0,
    )

    response = test_client.post(
        "/orders/quote",
        json={
            "shop_id": str(ids["shop_id"]),
            "order_info": [{"product_id": str(product_id), "product_name": "VAT example", "quantity": 1}],
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["order_info"][0]["price"] == 121.0
    assert response.json()["subtotal"] == 121.0
    assert response.json()["total"] == 121.0

    order_response = test_client.post(
        "/orders/",
        json={
            "shop_id": str(ids["shop_id"]),
            "account_name": "vat-example@example.com",
            "order_info": [{"product_id": str(product_id), "product_name": "VAT example", "quantity": 1}],
        },
    )
    assert order_response.status_code == 201, order_response.json()
    assert order_response.json()["total"] == 121.0


def test_quote_order_skips_shipping_for_non_shippable_product(shop_shipping_fixed_with_products, test_client):
    ids = shop_shipping_fixed_with_products
    category = make_category(shop_id=ids["shop_id"])
    product_id = make_product(
        shop_id=ids["shop_id"],
        category_id=category,
        main_name="Digital product",
        price=10.0,
        shippable=False,
    )

    response = test_client.post(
        "/orders/quote",
        json={
            "shop_id": str(ids["shop_id"]),
            "order_info": [{"product_id": str(product_id), "product_name": "Digital product", "quantity": 1}],
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["shipping_fee_inc_btw"] is None
    assert response.json()["total"] == response.json()["subtotal"]


def test_quote_and_create_order_check_stock_when_enabled(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    shop = db.session.get(ShopTable, ids["shop_id"])
    shop.config = {"toggles": {"enable_stock_on_products": True}}
    db.session.commit()

    body = _order_body(
        ids["shop_id"],
        [{"product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2}],
    )
    assert (
        test_client.post(
            "/orders/quote", json={"shop_id": body["shop_id"], "order_info": body["order_info"]}
        ).status_code
        == 400
    )
    assert test_client.post("/orders/", json=body).status_code == 400


def test_order_rejects_mixed_payment_plans(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    response = test_client.post(
        "/orders/",
        json=_order_body(
            ids["shop_id"],
            [
                {"product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1, "plan": "onetime"},
                {"product_id": str(ids["p2"]), "product_name": "Item 2", "quantity": 1, "plan": "monthly"},
            ],
        ),
    )
    assert response.status_code == 422, response.json()


def test_order_customer_ids_increment_per_shop(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    body = _order_body(
        ids["shop_id"],
        [{"product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1}],
    )
    first = test_client.post("/orders/", json=body)
    second = test_client.post("/orders/", json=body)

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()
    assert first.json()["customer_order_id"] == 1
    assert second.json()["customer_order_id"] == 2


def test_patch_order_sets_completed_at(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    response = test_client.post(
        "/orders/",
        json=_order_body(
            ids["shop_id"],
            [{"product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1}],
        ),
    )
    assert response.status_code == 201, response.json()

    response = test_client.patch(f"/orders/{response.json()['id']}", json={"status": "cancelled"})
    assert response.status_code == 201, response.json()

    order = db.session.get(OrderTable, response.json()["id"])
    assert order.status == "cancelled"
    assert order.completed_at is not None


def test_create_order_with_shipping_single_rate(shop_shipping_fixed_with_products, test_client):
    ids = shop_shipping_fixed_with_products
    items = [
        {"description": "x", "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # fixed_fee=4.95 is ex-VAT; with 21% VAT → 5.99 inc
    assert j["shipping_fee_inc_btw"] == 5.99
    # items_total = 24.20 including VAT; total = 24.20 + 5.99
    assert j["total"] == 30.19


def test_create_order_with_shipping_mixed_vat(shop_shipping_mixed_vat, test_client):
    ids = shop_shipping_mixed_vat
    items = [
        {"description": "x", "product_id": str(ids["p_high"]), "product_name": "Std", "quantity": 1},
        {"description": "x", "product_id": str(ids["p_low"]), "product_name": "Low", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # fixed_fee=10.0 ex-VAT is allocated 50/50 across the 100/100 net cart split.
    assert j["shipping_fee_inc_btw"] == 11.5
    assert j["total"] == 241.5


def test_create_order_free_shipping_threshold(shop_shipping_free_above, test_client):
    ids = shop_shipping_free_above
    # Cart total inc-VAT = 72.60, threshold = 50 -> shipping should be 0
    items = [
        {"description": "x", "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 6},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    assert j["shipping_fee_inc_btw"] == 0.0
    assert j["total"] == 72.6


def test_create_order_below_free_shipping_threshold(shop_shipping_free_above, test_client):
    ids = shop_shipping_free_above
    # Cart total inc-VAT = 36.30, threshold = 50 -> shipping should apply
    items = [
        {"description": "x", "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 3},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # 4.95 ex-VAT @ 21% → 5.99 inc; products are 36.30 inc
    assert j["shipping_fee_inc_btw"] == 5.99
    assert j["total"] == 42.29


def test_create_order_rejects_client_supplied_price(shop_shipping_fixed_with_products, test_client):
    ids = shop_shipping_fixed_with_products
    items = [
        {"description": "x", "price": 0.01, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 422, response.json()


def test_order_updates_reject_client_prices(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    response = test_client.post(
        "/orders/",
        json=_order_body(
            ids["shop_id"],
            [{"product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1}],
        ),
    )
    assert response.status_code == 201, response.json()

    update_response = test_client.patch(f"/orders/{response.json()['id']}", json={"total": 0.01})
    assert update_response.status_code == 422, update_response.json()


@pytest.fixture()
def shop_shipping_vat_bypass_with_products():
    shop_id = make_shop_with_shipping(fixed_fee=5.00, vat_calculation_enabled=False)
    category = make_category(shop_id=shop_id)
    p1 = make_product(shop_id=shop_id, category_id=category, main_name="Item 1", price=10.0)
    return {"shop_id": shop_id, "p1": p1}


def test_create_order_vat_bypass_adds_flat_fee(shop_shipping_vat_bypass_with_products, test_client):
    """With VAT bypass on, configured fee is added to total without VAT calc."""
    ids = shop_shipping_vat_bypass_with_products
    items = [
        {"description": "x", "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # Configured 5.00 added flat (no VAT split, no per-rate inflation)
    assert j["shipping_fee_inc_btw"] == 5.0
    assert j["total"] == 29.2


def test_create_order_uses_active_discount_and_persists_gross_price(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    category = make_category(shop_id=ids["shop_id"])
    product_id = make_product(
        shop_id=ids["shop_id"],
        category_id=category,
        main_name="Discounted",
        price=100.0,
        discounted_price=50.0,
        discounted_from=datetime.now() - timedelta(days=1),
        discounted_to=datetime.now() + timedelta(days=1),
    )
    response = test_client.post(
        "/orders/",
        json=_order_body(
            ids["shop_id"],
            [{"product_id": str(product_id), "product_name": "Discounted", "quantity": 1}],
        ),
    )
    assert response.status_code == 201, response.json()
    order = test_client.get(f"/orders/{response.json()['id']}").json()
    assert order["total"] == 60.5
    assert order["order_info"][0]["price"] == 60.5


def test_create_order_uses_selected_recurring_plan(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    category = make_category(shop_id=ids["shop_id"])
    product_id = make_product(
        shop_id=ids["shop_id"],
        category_id=category,
        main_name="Subscription",
        price=100.0,
        recurring_price_monthly=10.0,
    )
    response = test_client.post(
        "/orders/",
        json=_order_body(
            ids["shop_id"],
            [{"product_id": str(product_id), "product_name": "Subscription", "quantity": 1, "plan": "monthly"}],
        ),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["total"] == 12.1


# --- DELETE /orders/{order_id} is admin-only -----------------------------------
#
# The route has no shop in its path, so nothing can bind the caller to the order's
# shop. Until the order-management routes are reworked, deleting is for admins.


def test_delete_order_refuses_a_shop_user(shop, pending_order, as_cognito_user):
    client = as_cognito_user([str(shop)])  # a user attached to the order's own shop, not an admin

    assert client.delete(f"/orders/{pending_order.id}").status_code == 403
    assert OrderTable.query.filter_by(id=pending_order.id).first() is not None


def test_delete_order_as_admin(pending_order, test_client):
    assert test_client.delete(f"/orders/{pending_order.id}").status_code == 204
    assert OrderTable.query.filter_by(id=pending_order.id).first() is None


# --- PATCH /orders/{order_id} must be atomic and safe against double submits (shop-poc#349) ---


@pytest.fixture()
def real_db(db_session):
    """Sessions on their own pooled connections, committing for real.

    The ``db_session`` fixture binds every session to one connection inside an
    outer transaction. That serializes concurrent requests by itself, and a request
    session that is closed there cannot roll back either (SQLAlchemy joins the
    outer transaction in "rollback_only" mode). Tests that need either behaviour
    use this fixture and register the shops they create, so their rows can be
    deleted afterwards, which the outer rollback can't do for them.
    """
    wrapped = db.wrapped_database
    original_factory, original_scoped = wrapped.session_factory, wrapped.scoped_session
    wrapped.session_factory = sessionmaker(**SESSION_ARGUMENTS, bind=wrapped.engine)
    wrapped.scoped_session = scoped_session(wrapped.session_factory, wrapped._scopefunc)
    BaseModel.set_query(cast(SearchQuery, wrapped.scoped_session.query_property()))

    shop_ids: list = []
    try:
        yield shop_ids
    finally:
        wrapped.scoped_session.remove()
        with wrapped.engine.begin() as conn:
            for shop_id in shop_ids:
                params = {"s": str(shop_id)}
                conn.execute(text("DELETE FROM orders WHERE shop_id = :s"), params)
                conn.execute(text("DELETE FROM accounts WHERE shop_id = :s"), params)
                conn.execute(
                    text(
                        "DELETE FROM product_translations "
                        "WHERE product_id IN (SELECT id FROM products WHERE shop_id = :s)"
                    ),
                    params,
                )
                conn.execute(text("DELETE FROM products WHERE shop_id = :s"), params)
                conn.execute(
                    text(
                        "DELETE FROM category_translations "
                        "WHERE category_id IN (SELECT id FROM categories WHERE shop_id = :s)"
                    ),
                    params,
                )
                conn.execute(text("DELETE FROM categories WHERE shop_id = :s"), params)
                conn.execute(text("DELETE FROM shops WHERE id = :s"), params)
        wrapped.session_factory, wrapped.scoped_session = original_factory, original_scoped
        BaseModel.set_query(cast(SearchQuery, original_scoped.query_property()))


def _shop_with_stocked_order(stock: int = 5, cleanup: list | None = None) -> dict:
    """A shop with stock tracking on, two products and one pending order for one of each."""
    shop_id = make_shop_with_shipping(enabled=False)
    if cleanup is not None:
        cleanup.append(shop_id)
    shop = db.session.get(ShopTable, shop_id)
    shop.config = {**shop.config, "toggles": {**shop.config["toggles"], "enable_stock_on_products": True}}
    db.session.commit()

    account = make_account(shop_id=shop_id, name=f"buyer-{shop_id}@example.com")
    category = make_category(shop_id=shop_id)
    p1 = make_product(shop_id=shop_id, category_id=category, main_name="Item 1", stock=stock)
    p2 = make_product(shop_id=shop_id, category_id=category, main_name="Item 2", stock=stock)
    order = make_pending_order(shop_id=shop_id, account_id=account, product_id_1=p1, product_id_2=p2)
    return {"shop_id": shop_id, "order_id": order.id, "p1": p1, "p2": p2}


def _capture_confirmation_emails(monkeypatch) -> list:
    sent: list = []
    monkeypatch.setattr(mail_settings, "SHOP_MAIL_ENABLED", True)
    monkeypatch.setattr(public, "send_order_confirmation_emails", lambda **kwargs: sent.append(kwargs))
    return sent


def _stock(product_id) -> int:
    db.session.expire_all()
    return db.session.get(ProductTable, product_id).stock


def test_patch_order_complete_twice_deducts_stock_and_mails_once(test_client, monkeypatch):
    ids = _shop_with_stocked_order()
    sent = _capture_confirmation_emails(monkeypatch)

    first = test_client.patch(f"/orders/{ids['order_id']}", json={"status": "complete"})
    second = test_client.patch(f"/orders/{ids['order_id']}", json={"status": "complete"})

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()
    assert _stock(ids["p1"]) == 4
    assert _stock(ids["p2"]) == 4
    assert len(sent) == 1


def test_patch_order_complete_rolls_back_when_a_product_is_missing(test_client, monkeypatch, real_db):
    """Status change, stock deduction and notifications are one unit: if any product
    lookup fails nothing is persisted and nothing is sent.
    """
    ids = _shop_with_stocked_order(cleanup=real_db)
    sent = _capture_confirmation_emails(monkeypatch)

    order = db.session.get(OrderTable, ids["order_id"])
    # Sorts after any uuid4, so the first product is deducted in-session before this one 404s.
    order.order_info = [
        *order.order_info[:1],
        {**order.order_info[1], "product_id": "ffffffff-ffff-4fff-8fff-ffffffffffff"},
    ]
    db.session.commit()

    response = test_client.patch(f"/orders/{ids['order_id']}", json={"status": "complete"})

    assert response.status_code == 404, response.json()
    db.session.expire_all()
    order = db.session.get(OrderTable, ids["order_id"])
    assert order.status == "pending"
    assert order.completed_at is None
    assert _stock(ids["p1"]) == 5
    assert sent == []


def test_concurrent_patch_order_complete_deducts_stock_and_mails_once(test_client, monkeypatch, real_db):
    """Two overlapping PATCH complete calls (double submit, retry, Stripe redirect)
    must deduct stock and send the confirmation email exactly once.
    """
    ids = _shop_with_stocked_order(cleanup=real_db)
    sent = _capture_confirmation_emails(monkeypatch)

    # Hold each request between its order read and its commit, so both are
    # in flight at once: without a row lock both would see "pending".
    original_shop_get = shop_crud.get

    def slow_shop_get(*args, **kwargs):
        time.sleep(0.5)
        return original_shop_get(*args, **kwargs)

    monkeypatch.setattr(shop_crud, "get", slow_shop_get)

    barrier = threading.Barrier(2)
    responses: list = []

    def complete_order():
        barrier.wait()
        responses.append(test_client.patch(f"/orders/{ids['order_id']}", json={"status": "complete"}))

    threads = [threading.Thread(target=complete_order) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert [r.status_code for r in responses] == [201, 201], [r.json() for r in responses]
    assert _stock(ids["p1"]) == 4
    assert _stock(ids["p2"]) == 4
    assert len(sent) == 1
