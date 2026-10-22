"""Statement budgets for the hot read paths.

The 2026-10-19 incident exhausted the connection pool while Postgres sat idle: the catalogue endpoints issued a
couple of SQL statements *per product* (lazy translation, category, tag and attribute loads) and held their
pooled connection for the whole walk. These tests pin the fix: each endpoint's statement count must not grow with
the catalogue, and must stay under a small fixed budget. If one fails after you touched a model or an endpoint,
you most likely re-introduced a lazy load per row; see ``server/crud/crud_product.py`` for the loader bundles.
"""

import pytest

from server.db import db
from server.db.models import ProductToTagTable
from tests.unit_tests.factories.account import make_account
from tests.unit_tests.factories.attribute import make_attribute_with_translation, make_option, make_pav
from tests.unit_tests.factories.categories import make_category_translated
from tests.unit_tests.factories.order import make_pending_order
from tests.unit_tests.factories.product import make_translated_product
from tests.unit_tests.factories.shop import make_shop
from tests.unit_tests.factories.tag import make_tag

SMALL = (1, 2)  # categories, products per category
LARGE = (3, 4)


def _catalogue(categories: int, products_per_category: int) -> dict:
    """A shop whose every product has a translated category, two tags and two translated attributes."""
    shop_id = make_shop(with_config=True, random_shop_name=True)
    tag_ids = [make_tag(shop_id, main_name=f"tag {i}") for i in range(2)]
    size_id = make_attribute_with_translation(shop_id, name="size", main_name="Maat")
    colour_id = make_attribute_with_translation(shop_id, name="colour", main_name="Kleur")
    size_options = [make_option(size_id, value) for value in ("S", "M")]
    colour_options = [make_option(colour_id, value) for value in ("RED", "BLUE")]

    category_ids = []
    product_ids = []
    for c in range(categories):
        category_id = make_category_translated(shop_id, main_name=f"category {c}")
        category_ids.append(category_id)
        for p in range(products_per_category):
            product_id = make_translated_product(shop_id, category_id, main_name=f"product {c}-{p}")
            make_pav(product_id, size_id, size_options[p % 2])
            make_pav(product_id, colour_id, colour_options[p % 2])
            for tag_id in tag_ids:
                db.session.add(ProductToTagTable(shop_id=shop_id, product_id=product_id, tag_id=tag_id))
            db.session.commit()
            product_ids.append(product_id)
    return {"shop_id": shop_id, "category_ids": category_ids, "product_ids": product_ids}


def _count(query_counter, test_client, method: str, url: str, **kwargs) -> int:
    query_counter.clear()
    response = getattr(test_client, method)(url, **kwargs)
    assert response.status_code == 200, response.text
    return len(query_counter)


def _assert_flat(counts: dict[tuple, int], budget: int) -> None:
    small, large = counts[SMALL], counts[LARGE]
    assert small == large, f"statement count grows with the catalogue: {counts}"
    assert large <= budget, f"{large} statements, budget {budget}"


@pytest.mark.parametrize("lang", ["main", "alt1"])
def test_pricelist_statement_count_is_flat(query_counter, test_client, lang):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        counts[size] = _count(query_counter, test_client, "get", f"/shops/{shop['shop_id']}/prices/?lang={lang}")
    _assert_flat(counts, budget=8)


def test_cart_pricelist_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        body = {"products": [str(product_id) for product_id in shop["product_ids"]]}
        counts[size] = _count(
            query_counter, test_client, "post", f"/shops/{shop['shop_id']}/prices/?lang=alt1", json=body
        )
    _assert_flat(counts, budget=8)


def test_product_list_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        counts[size] = _count(query_counter, test_client, "get", f"/shops/{shop['shop_id']}/products/")
    _assert_flat(counts, budget=4)


def test_products_with_attributes_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        counts[size] = _count(query_counter, test_client, "get", f"/shops/{shop['shop_id']}/products/with_attributes")
    _assert_flat(counts, budget=8)


def test_category_products_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        url = f"/shops/{shop['shop_id']}/categories/{shop['category_ids'][0]}/products"
        counts[size] = _count(query_counter, test_client, "get", url)
    _assert_flat(counts, budget=9)


def test_single_product_with_attributes_is_a_handful_of_statements(query_counter, test_client):
    shop = _catalogue(*SMALL)
    url = f"/shops/{shop['shop_id']}/products/{shop['product_ids'][0]}/with_attributes"
    assert _count(query_counter, test_client, "get", url) <= 6


def test_order_quote_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        body = {
            "shop_id": str(shop["shop_id"]),
            "order_info": [
                {"product_id": str(product_id), "product_name": "p", "quantity": 1}
                for product_id in shop["product_ids"]
            ],
        }
        counts[size] = _count(query_counter, test_client, "post", "/orders/quote", json=body)
    _assert_flat(counts, budget=4)


def test_pending_orders_list_statement_count_is_flat(query_counter, test_client):
    counts = {}
    for size in (SMALL, LARGE):
        shop = _catalogue(*size)
        for i, product_id in enumerate(shop["product_ids"]):
            account_id = make_account(shop["shop_id"], name=f"customer {i}")
            make_pending_order(shop["shop_id"], account_id, product_id, product_id, customer_order_id=i)
        counts[size] = _count(query_counter, test_client, "get", f"/orders/shop/{shop['shop_id']}/pending")
    _assert_flat(counts, budget=5)
