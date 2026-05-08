import uuid

import pytest

from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.shop import make_shop, make_shop_with_shipping


@pytest.fixture()
def shop_no_shipping_config():
    # Default factory: shop.config = "{}" (no "shipping" key)
    shop_id = make_shop(with_config=False)
    category = make_category(shop_id=shop_id)
    p = make_product(shop_id=shop_id, category_id=category, price=10.0)
    return {"shop_id": shop_id, "p": p}


@pytest.fixture()
def shop_shipping_disabled_in_config():
    shop_id = make_shop_with_shipping(enabled=False, fixed_fee=4.95)
    category = make_category(shop_id=shop_id)
    p = make_product(shop_id=shop_id, category_id=category, price=10.0)
    return {"shop_id": shop_id, "p": p}


@pytest.fixture()
def shop_shipping_fixed():
    shop_id = make_shop_with_shipping(fixed_fee=4.95)
    category = make_category(shop_id=shop_id)
    p = make_product(shop_id=shop_id, category_id=category, price=10.0)
    return {"shop_id": shop_id, "p": p}


@pytest.fixture()
def shop_shipping_mixed():
    # 100 inc-VAT @ 21% + 100 inc-VAT @ 9% in cart, 10 EUR shipping inc-VAT
    shop_id = make_shop_with_shipping(fixed_fee=10.0)
    category = make_category(shop_id=shop_id)
    p_high = make_product(shop_id=shop_id, category_id=category, price=100.0, tax_category="vat_standard")
    p_low = make_product(shop_id=shop_id, category_id=category, price=100.0, tax_category="vat_lower_1")
    return {"shop_id": shop_id, "p_high": p_high, "p_low": p_low}


@pytest.fixture()
def shop_shipping_with_threshold():
    shop_id = make_shop_with_shipping(
        fixed_fee=4.95,
        free_shipping_above_enabled=True,
        free_shipping_above_amount=50.0,
    )
    category = make_category(shop_id=shop_id)
    p = make_product(shop_id=shop_id, category_id=category, price=10.0)
    return {"shop_id": shop_id, "p": p}


@pytest.fixture()
def shop_shipping_vat_bypass():
    shop_id = make_shop_with_shipping(fixed_fee=5.00, vat_calculation_enabled=False)
    category = make_category(shop_id=shop_id)
    p = make_product(shop_id=shop_id, category_id=category, price=10.0)
    return {"shop_id": shop_id, "p": p}


@pytest.fixture()
def shop_shipping_vat_bypass_mixed():
    shop_id = make_shop_with_shipping(fixed_fee=5.00, vat_calculation_enabled=False)
    category = make_category(shop_id=shop_id)
    p_high = make_product(shop_id=shop_id, category_id=category, price=100.0, tax_category="vat_standard")
    p_low = make_product(shop_id=shop_id, category_id=category, price=100.0, tax_category="vat_lower_1")
    return {"shop_id": shop_id, "p_high": p_high, "p_low": p_low}


def _calc_body(shop_id, items):
    return {"shop_id": str(shop_id), "order_info": items}


def test_calculate_unknown_shop_returns_404(test_client):
    body = {"shop_id": str(uuid.uuid4()), "order_info": []}
    response = test_client.post("/shipping/calculate", json=body)
    assert response.status_code == 404


def test_calculate_no_shipping_in_config(shop_no_shipping_config, test_client):
    ids = shop_no_shipping_config
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 1}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is False
    assert j["fee_inc_btw"] == 0.0
    assert j["lines"] == []


def test_calculate_shipping_disabled(shop_shipping_disabled_in_config, test_client):
    ids = shop_shipping_disabled_in_config
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 1}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is False
    assert j["fee_inc_btw"] == 0.0


def test_calculate_shipping_fixed_single_rate(shop_shipping_fixed, test_client):
    ids = shop_shipping_fixed
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 2}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    assert j["method"] == "fixed"
    # fixed_fee=4.95 is now ex-VAT; with 21% VAT → inc = 4.95 * 1.21 = 5.9895 → 5.99
    assert j["fee_ex_btw"] == 4.95
    assert j["fee_inc_btw"] == 5.99
    assert len(j["lines"]) == 1
    line = j["lines"][0]
    assert line["btw_rate"] == 21.0
    assert line["amount_ex_btw"] == 4.95
    assert line["amount_inc_btw"] == 5.99
    assert line["amount_btw"] == round(5.99 - 4.95, 2)
    # Sums reconcile
    assert round(j["fee_ex_btw"] + j["fee_btw"], 2) == j["fee_inc_btw"]


def test_calculate_shipping_mixed_vat(shop_shipping_mixed, test_client):
    ids = shop_shipping_mixed
    items = [
        {"description": "x", "price": 100.0, "product_id": str(ids["p_high"]), "product_name": "h", "quantity": 1},
        {"description": "x", "price": 100.0, "product_id": str(ids["p_low"]), "product_name": "l", "quantity": 1},
    ]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    # fixed_fee=10.0 is now ex-VAT, allocated 50/50 (5.00 ex per rate),
    # then VAT added: 5*1.21=6.05, 5*1.09=5.45 → fee_inc = 11.50, fee_ex = 10.00
    assert j["fee_ex_btw"] == 10.0
    assert j["fee_inc_btw"] == 11.5
    assert len(j["lines"]) == 2
    rates = sorted(line["btw_rate"] for line in j["lines"])
    assert rates == [9.0, 21.0]
    by_rate = {line["btw_rate"]: line for line in j["lines"]}
    assert by_rate[21.0]["amount_ex_btw"] == 5.0
    assert by_rate[21.0]["amount_inc_btw"] == 6.05
    assert by_rate[9.0]["amount_ex_btw"] == 5.0
    assert by_rate[9.0]["amount_inc_btw"] == 5.45
    ex_sum = round(sum(line["amount_ex_btw"] for line in j["lines"]), 2)
    assert ex_sum == 10.0


def test_calculate_free_shipping_threshold_met(shop_shipping_with_threshold, test_client):
    ids = shop_shipping_with_threshold
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 6}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    assert j["fee_inc_btw"] == 0.0
    assert j["free_shipping_applied"] is True
    assert j["free_shipping_threshold"] == 50.0
    assert j["lines"] == []


def test_calculate_free_shipping_threshold_not_met(shop_shipping_with_threshold, test_client):
    ids = shop_shipping_with_threshold
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 3}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    # fixed_fee=4.95 is ex-VAT; with 21% VAT → 5.99 inc
    assert j["fee_ex_btw"] == 4.95
    assert j["fee_inc_btw"] == 5.99
    assert j["free_shipping_applied"] is False
    assert j["free_shipping_threshold"] == 50.0


def test_calculate_shipping_vat_bypass_single_rate(shop_shipping_vat_bypass, test_client):
    ids = shop_shipping_vat_bypass
    items = [{"description": "x", "price": 10.0, "product_id": str(ids["p"]), "product_name": "p", "quantity": 1}]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    # VAT bypass: configured 5.00 added flat, no per-rate split
    assert j["fee_ex_btw"] == 5.0
    assert j["fee_inc_btw"] == 5.0
    assert j["fee_btw"] == 0.0
    assert j["lines"] == []


def test_calculate_shipping_vat_bypass_mixed_rates(shop_shipping_vat_bypass_mixed, test_client):
    """With VAT bypass on, mixed cart VAT rates don't trigger any split."""
    ids = shop_shipping_vat_bypass_mixed
    items = [
        {"description": "x", "price": 100.0, "product_id": str(ids["p_high"]), "product_name": "h", "quantity": 1},
        {"description": "x", "price": 100.0, "product_id": str(ids["p_low"]), "product_name": "l", "quantity": 1},
    ]
    response = test_client.post("/shipping/calculate", json=_calc_body(ids["shop_id"], items))
    assert response.status_code == 200
    j = response.json()
    assert j["enabled"] is True
    assert j["fee_ex_btw"] == 5.0
    assert j["fee_inc_btw"] == 5.0
    assert j["fee_btw"] == 0.0
    assert j["lines"] == []
