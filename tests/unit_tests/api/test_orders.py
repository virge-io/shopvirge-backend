from uuid import uuid4

import pytest

from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop_with_shipping


def test_orders_get_multi(shop, pending_order, test_client):
    response = test_client.get(f"/orders/")
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


def _order_body(shop_id, items, total=0.0):
    body = {
        "shop_id": str(shop_id),
        "order_info": items,
        "account_name": f"buyer-{shop_id}@example.com",
        "notes": "test",
        "status": "pending",
        "customer_order_id": 1,
        "total": total,
    }
    return body


def test_create_order_no_shipping(shop_no_shipping_with_products, test_client):
    ids = shop_no_shipping_with_products
    items = [
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
        {"description": "x", "price": 20.0, "product_id": str(ids["p2"]), "product_name": "Item 2", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items, total=999.0)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    assert j["shipping_fee_inc_btw"] is None
    # items_total = 10*2 + 20*1 = 40; client-sent total ignored
    assert j["total"] == 40.0


def test_create_order_with_shipping_single_rate(shop_shipping_fixed_with_products, test_client):
    ids = shop_shipping_fixed_with_products
    items = [
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # fixed_fee=4.95 is ex-VAT; with 21% VAT → 5.99 inc
    assert j["shipping_fee_inc_btw"] == 5.99
    # items_total = 20; total = 20 + 5.99
    assert j["total"] == 25.99


def test_create_order_with_shipping_mixed_vat(shop_shipping_mixed_vat, test_client):
    ids = shop_shipping_mixed_vat
    items = [
        {"description": "x", "price": 100.0, "product_id": str(ids["p_high"]), "product_name": "Std", "quantity": 1},
        {"description": "x", "price": 100.0, "product_id": str(ids["p_low"]), "product_name": "Low", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # fixed_fee=10.0 ex-VAT split 50/50 → 5*1.21 + 5*1.09 = 11.50 inc
    assert j["shipping_fee_inc_btw"] == 11.5
    # items_total = 200; total = 200 + 11.50
    assert j["total"] == 211.5


def test_create_order_free_shipping_threshold(shop_shipping_free_above, test_client):
    ids = shop_shipping_free_above
    # Cart total inc-VAT = 60, threshold = 50 -> shipping should be 0
    items = [
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 6},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    assert j["shipping_fee_inc_btw"] == 0.0
    assert j["total"] == 60.0


def test_create_order_below_free_shipping_threshold(shop_shipping_free_above, test_client):
    ids = shop_shipping_free_above
    # Cart total inc-VAT = 30, threshold = 50 -> shipping should apply
    items = [
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 3},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # 4.95 ex-VAT @ 21% → 5.99 inc
    assert j["shipping_fee_inc_btw"] == 5.99
    assert j["total"] == 35.99


def test_create_order_client_total_overridden(shop_shipping_fixed_with_products, test_client):
    ids = shop_shipping_fixed_with_products
    items = [
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 1},
    ]
    body = _order_body(ids["shop_id"], items, total=1.0)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # Client sent total=1.0 but server should override with items + shipping = 10 + 5.99
    assert j["total"] == 15.99
    assert j["shipping_fee_inc_btw"] == 5.99


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
        {"description": "x", "price": 10.0, "product_id": str(ids["p1"]), "product_name": "Item 1", "quantity": 2},
    ]
    body = _order_body(ids["shop_id"], items)
    response = test_client.post("/orders/", json=body)
    assert response.status_code == 201, response.json()
    j = response.json()
    # Configured 5.00 added flat (no VAT split, no per-rate inflation)
    assert j["shipping_fee_inc_btw"] == 5.0
    assert j["total"] == 25.0
