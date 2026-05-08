import pytest

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


# from server.api.endpoints.shop_endpoints.orders import get_price_rules_total
# from server.crud.crud_order import order_crud
# from server.schemas.order import OrderItem
#
#
# def test_order_list(test_client, shop_with_orders, superuser_token_headers):
#     response = test_client.get(f"/api/orders", headers=superuser_token_headers)
#     assert response.status_code == 200
#     assert len(response.json()) == 2
#
#
# def test_mixed_order_list(test_client, shop_with_mixed_orders, superuser_token_headers):
#     response = test_client.get(f"/api/orders", headers=superuser_token_headers)
#     assert response.status_code == 200
#     assert len(response.json()) == 2
#
#
# def test_orders_pending_list(test_client, shop_with_different_statuses_orders, shop_1, superuser_token_headers):
#     response = test_client.get(f"/api/orders/shop/{shop_1.id}/pending", headers=superuser_token_headers)
#     response_json = response.json()
#     assert response.status_code == 200
#     assert len(response_json) == 1
#     assert response_json[0]["status"] == "pending"
#
#
# def test_orders_complete_list(test_client, shop_with_different_statuses_orders, shop_1, superuser_token_headers):
#     response = test_client.get(f"/api/orders/shop/{shop_1.id}/complete", headers=superuser_token_headers)
#     response_json = response.json()
#     assert response.status_code == 200
#     assert len(response_json) == 2
#     assert response_json[0]["status"] == "complete"
#     assert response_json[1]["status"] == "cancelled"
#
#
# def test_create_order(test_client, price_1, price_2, kind_1, kind_2, shop_with_products):
#     items = [
#         {
#             "description": "1 gram",
#             "price": price_1.one,
#             "kind_id": str(kind_1.id),
#             "kind_name": kind_1.name,
#             "internal_product_id": "01",
#             "quantity": 2,
#         },
#         {
#             "description": "1 joint",
#             "price": price_2.joint,
#             "kind_id": str(kind_2.id),
#             "kind_name": kind_2.name,
#             "internal_product_id": "02",
#             "quantity": 1,
#         },
#     ]
#     body = {
#         "shop_id": str(shop_with_products.id),
#         "total": 24.0,  # 2x 1 gram of 10,- + 1 joint of 4
#         "order_info": items,
#     }
#     response = test_client.post(f"/api/orders", json=body)
#     assert response.status_code == 201, response.json()
#     response_json = response.json()
#     assert response_json["customer_order_id"] == 1
#     assert response_json["total"] == 24.0
#
#     order = order_crud.get_first_order_filtered_by(customer_order_id=1)
#     assert order.shop_id == shop_with_products.id
#     assert order.total == 24.0
#     assert order.customer_order_id == 1
#     assert order.status == "pending"
#     assert order.order_info == items
#
#     # test with a second order to also cover the automatic increase of `customer_order_id`
#     response = test_client.post(f"/api/orders", json=body)
#     response_json = response.json()
#     assert response_json["customer_order_id"] == 2
#     assert response_json["total"] == 24.0
#
#     assert response.status_code == 201
#     order = order_crud.get_first_order_filtered_by(customer_order_id=2)
#     assert order.customer_order_id == 2
#
#
# def test_create_mixed_order(test_client, price_1, price_2, price_3, product_1, kind_1, kind_2, shop_with_products):
#     items = [
#         {
#             "description": "1 gram",
#             "price": price_1.one,
#             "kind_id": str(kind_1.id),
#             "kind_name": kind_1.name,
#             "internal_product_id": "01",
#             "quantity": 2,
#         },
#         {
#             "description": "1 joint",
#             "price": price_2.joint,
#             "kind_id": str(kind_2.id),
#             "kind_name": kind_2.name,
#             "internal_product_id": "02",
#             "quantity": 1,
#         },
#         {
#             "description": "1",
#             "price": price_3.piece,
#             "product_id": str(product_1.id),
#             "product_name": product_1.name,
#             "internal_product_id": "03",
#             "quantity": 1,
#         },
#     ]
#     body = {
#         "shop_id": str(shop_with_products.id),
#         "total": 26.50,  # 2x 1 gram of 10,- + 1 joint of 4 + 1 cola (2.50)
#         "order_info": items,
#     }
#     response = test_client.post(f"/api/orders", json=body)
#     assert response.status_code == 201, response.json
#     response_json = response.json()
#     assert response_json["customer_order_id"] == 1
#     assert response_json["total"] == 26.50
#
#     order = order_crud.get_first_order_filtered_by(customer_order_id=1)
#     assert order.shop_id == shop_with_products.id
#     assert order.total == 26.50
#     assert order.customer_order_id == 1
#     assert order.status == "pending"
#     assert order.order_info == items
#
#     # test with a second order to also cover the automatic increase of `customer_order_id`
#     response = test_client.post(f"/api/orders", json=body)
#     response_json = response.json()
#     assert response_json["customer_order_id"] == 2
#     assert response_json["total"] == 26.50
#
#     assert response.status_code == 201, response.json
#     order = order_crud.get_first_order_filtered_by(customer_order_id=2)
#     assert order.customer_order_id == 2
#
#
# def test_create_order_validation(test_client, price_1, price_2, kind_1, kind_2, shop_with_products):
#     items = [
#         {
#             "description": "1 gram",
#             "price": price_1.one,
#             "kind_id": str(kind_1.id),
#             "kind_name": kind_1.name,
#             "internal_product_id": "01",
#             "quantity": 2,
#         },
#         {
#             "description": "1 joint",
#             "price": price_2.joint,
#             "kind_id": str(kind_2.id),
#             "kind_name": kind_2.name,
#             "internal_product_id": "02",
#             "quantity": 1,
#         },
#     ]
#     # Wrong shop_id
#     data = {
#         "shop_id": "afda6a2f-293d-4d76-a4f9-1a2d08b56835",
#         "total": 24.0,  # 2x 1 gram of 10,- + 1 joint of 4
#         "notes": "Nice one",
#         "order_info": items,
#     }
#     response = test_client.post(f"/api/orders", json=data)
#     assert response.status_code == 404
#
#     # No shop_id
#     data = {"total": 24.0, "notes": "Nice one", "order_info": items}  # 2x 1 gram of 10,- + 1 joint of 4
#     response = test_client.post(f"/api/orders", json=data)
#     assert response.status_code == 422
#
#     # Todo: test checksum functionality (totals should match with quantity in items)
#
#
# def test_price_rules():
#     order_info = [
#         OrderItem(
#             description="1 gram",
#             price=8,
#             kind_id="fd2f4ee4-a58e-425d-998b-003757b790eb",
#             kind_name="Soort 1",
#             product_id=None,
#             product_name=None,
#             internal_product_id="1",
#             quantity=1,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=25,
#             kind_id="593277e5-f301-4662-9cf5-488e2479bac0",
#             kind_name="Soort 2",
#             product_id=None,
#             product_name=None,
#             internal_product_id="47",
#             quantity=1,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=9,
#             kind_id="b13e26c3-834b-493f-a1d0-17859c41cea0",
#             kind_name="Soort 3",
#             product_id=None,
#             product_name=None,
#             internal_product_id="4",
#             quantity=1,
#         ),
#     ]
#
#     assert get_price_rules_total(order_info) == 3
#
#     # Check on quantity
#     order_info = [
#         OrderItem(
#             description="1 gram",
#             price=8,
#             kind_id="fd2f4ee4-a58e-425d-998b-003757b790eb",
#             kind_name="Soort 1",
#             product_id=None,
#             product_name=None,
#             internal_product_id="1",
#             quantity=4,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=25,
#             kind_id="593277e5-f301-4662-9cf5-488e2479bac0",
#             kind_name="Soort 2",
#             product_id=None,
#             product_name=None,
#             internal_product_id="47",
#             quantity=1,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=9,
#             kind_id="b13e26c3-834b-493f-a1d0-17859c41cea0",
#             kind_name="Soort 3",
#             product_id=None,
#             product_name=None,
#             internal_product_id="4",
#             quantity=1,
#         ),
#     ]
#     assert get_price_rules_total(order_info) == 6
#
#     # Check with 5g
#     order_info = [
#         OrderItem(
#             description="5 gram",
#             price=8,
#             kind_id="fd2f4ee4-a58e-425d-998b-003757b790eb",
#             kind_name="Soort 1",
#             product_id=None,
#             product_name=None,
#             internal_product_id="1",
#             quantity=1,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=25,
#             kind_id="593277e5-f301-4662-9cf5-488e2479bac0",
#             kind_name="Soort 2",
#             product_id=None,
#             product_name=None,
#             internal_product_id="47",
#             quantity=1,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=9,
#             kind_id="b13e26c3-834b-493f-a1d0-17859c41cea0",
#             kind_name="Soort 3",
#             product_id=None,
#             product_name=None,
#             internal_product_id="4",
#             quantity=1,
#         ),
#     ]
#     assert get_price_rules_total(order_info) == 7
#
#     # Check with joint
#     order_info = [
#         OrderItem(
#             description="1 gram",
#             price=8,
#             kind_id="fd2f4ee4-a58e-425d-998b-003757b790eb",
#             kind_name="Soort 1",
#             product_id=None,
#             product_name=None,
#             internal_product_id="1",
#             quantity=4,
#         ),
#         OrderItem(
#             description="1 gram",
#             price=25,
#             kind_id="593277e5-f301-4662-9cf5-488e2479bac0",
#             kind_name="Soort 2",
#             product_id=None,
#             product_name=None,
#             internal_product_id="47",
#             quantity=1,
#         ),
#         OrderItem(
#             description="joint",
#             price=6,
#             kind_id="a99f677f-14dc-4d67-9d41-ff3e85dd09fc",
#             kind_name="Mega Joint",
#             product_id=None,
#             product_name=None,
#             internal_product_id="26",
#             quantity=1,
#         ),
#     ]
#     assert get_price_rules_total(order_info) == 5.4
#
#
# def test_create_order_with_ip_allowed(test_client, price_1, kind_1, shop_with_testclient_ip_with_products):
#     items = [
#         {
#             "description": "1 gram",
#             "price": price_1.one,
#             "kind_id": str(kind_1.id),
#             "kind_name": kind_1.name,
#             "internal_product_id": "01",
#             "quantity": 2,
#         }
#     ]
#     body = {
#         "shop_id": str(shop_with_testclient_ip_with_products.id),
#         "total": 10.0,
#         "order_info": items,
#     }
#     response = test_client.post(f"/api/orders", json=body)
#     assert response.status_code == 201, response.json()
#     response_json = response.json()
#     assert response_json["customer_order_id"] == 1
#     assert response_json["total"] == 10.0
#
#     order = order_crud.get_first_order_filtered_by(customer_order_id=1)
#     assert order.shop_id == shop_with_testclient_ip_with_products.id
#     assert order.total == 10.0
#     assert order.customer_order_id == 1
#     assert order.status == "pending"
#     assert order.order_info == items
#
#
# def test_create_order_with_ip_not_allowed(test_client, price_1, kind_1, shop_with_custom_ip_with_products):
#     items = [
#         {
#             "description": "1 gram",
#             "price": price_1.one,
#             "kind_id": str(kind_1.id),
#             "kind_name": kind_1.name,
#             "internal_product_id": "01",
#             "quantity": 2,
#         }
#     ]
#     body = {
#         "shop_id": str(shop_with_custom_ip_with_products.id),
#         "total": 10.0,
#         "order_info": items,
#     }
#     response = test_client.post(f"/api/orders", json=body)
#     assert response.status_code == 400, response.json()
#     response_json = response.json()
#     assert response_json["detail"] == "NOT_ON_SHOP_WIFI"
#
#
# def test_patch_order_to_complete(test_client, shop_with_orders, superuser_token_headers):
#     # Get the uncompleted order_id from the fixture:
#     order = order_crud.get_first_order_filtered_by(status="pending")
#
#     body = {
#         "status": "complete",
#     }
#     response = test_client.patch(f"/api/orders/{order.id}", json=body, headers=superuser_token_headers)
#     assert response.status_code == 201
#
#     updated_order = test_client.get(f"/api/orders/{order.id}", headers=superuser_token_headers).json()
#     assert updated_order["status"] == "complete"
#     assert updated_order["completed_at"] is not None
#
#
# def test_update_order(test_client, shop_with_orders, superuser_token_headers):
#     # Get the completed order_id from the fixture:
#     order = order_crud.get_first_order_filtered_by(status="complete")
#
#     body = {"status": "cancelled", "order_info": order.order_info, "shop_id": str(order.shop_id)}
#     response = test_client.put(f"/api/orders/{order.id}", json=body, headers=superuser_token_headers)
#     assert response.status_code == 201
#
#     updated_order = test_client.get(f"/api/orders/{order.id}", headers=superuser_token_headers).json()
#     assert updated_order["status"] == "cancelled"
#
#
# def test_delete_order(test_client, shop_with_orders, superuser_token_headers):
#     order = order_crud.get_first_order_filtered_by(status="complete")
#
#     response = test_client.delete(f"/api/orders/{order.id}", headers=superuser_token_headers)
#     assert response.status_code == 204
#
#     orders = test_client.get("/api/orders", headers=superuser_token_headers).json()
#     assert 1 == len(orders)
