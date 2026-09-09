from http import HTTPStatus
from uuid import uuid4

from server.db import db
from server.db.models import ProductTable, ShopTable


def test_available_attributes_happy_path(test_client, shop_with_category_attributes):
    ids = shop_with_category_attributes
    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{ids['cat1_id']}/available-attributes")
    assert response.status_code == HTTPStatus.OK

    data = response.json()
    assert len(data) == 2

    attrs_by_name = {a["name"]: a for a in data}

    # Verify size attribute
    size = attrs_by_name["size"]
    assert size["id"] == str(ids["size_attr_id"])
    assert size["unit"] == "EU"
    assert size["translation"]["main_name"] == "Maat"
    assert size["translation"]["alt1_name"] == "Size"
    assert size["translation"]["alt2_name"] == "Taille"

    size_opts = {o["value_key"]: o for o in size["options"]}
    assert len(size_opts) == 3
    # prod1 has S, prod2 has S => count 2
    assert size_opts["S"]["product_count"] == 2
    # prod2 has M => count 1
    assert size_opts["M"]["product_count"] == 1
    # prod3 has L => count 1
    assert size_opts["L"]["product_count"] == 1

    # Verify color attribute
    color = attrs_by_name["color"]
    assert color["id"] == str(ids["color_attr_id"])
    assert color["translation"]["main_name"] == "Kleur"
    assert color["translation"]["alt1_name"] == "Color"

    color_opts = {o["value_key"]: o for o in color["options"]}
    assert len(color_opts) == 2
    # prod1 and prod2 have RED => count 2
    assert color_opts["RED"]["product_count"] == 2
    # prod3 has BLUE => count 1
    assert color_opts["BLUE"]["product_count"] == 1


def test_available_attributes_category_scoping(test_client, shop_with_category_attributes):
    """Category 2 only has 1 product with size M — should only return size with M option."""
    ids = shop_with_category_attributes
    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{ids['cat2_id']}/available-attributes")
    assert response.status_code == HTTPStatus.OK

    data = response.json()
    assert len(data) == 1

    attr = data[0]
    assert attr["name"] == "size"
    assert len(attr["options"]) == 1
    assert attr["options"][0]["value_key"] == "M"
    assert attr["options"][0]["product_count"] == 1


def test_available_attributes_empty_category(test_client, shop_with_category_attributes):
    """A category with no attribute values returns an empty list."""
    from tests.unit_tests.factories.categories import make_category

    ids = shop_with_category_attributes
    empty_cat_id = make_category(shop_id=ids["shop_id"], main_name="Empty", main_description="Empty category")

    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{empty_cat_id}/available-attributes")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


def test_available_attributes_excludes_products_without_price(test_client, shop_with_category_attributes):
    """Products with price=None should not be counted in attribute options."""
    ids = shop_with_category_attributes

    # Set prod3 (the only product with size L and color BLUE) to have no price
    _prod3 = db.session.query(ProductTable).filter(ProductTable.category_id == ids["cat1_id"]).all()
    # prod3 is the one with size L — find it via attribute values
    from server.db.models import ProductAttributeValueTable

    prod_with_l = (
        db.session.query(ProductAttributeValueTable.product_id)
        .filter(ProductAttributeValueTable.option_id == ids["size_l_id"])
        .scalar()
    )
    product = db.session.query(ProductTable).get(prod_with_l)
    product.price = None
    db.session.commit()

    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{ids['cat1_id']}/available-attributes")
    assert response.status_code == HTTPStatus.OK

    data = response.json()
    attrs_by_name = {a["name"]: a for a in data}

    # Size L and color BLUE should be gone (only prod3 had them)
    size_opts = {o["value_key"]: o for o in attrs_by_name["size"]["options"]}
    assert "L" not in size_opts
    assert size_opts["S"]["product_count"] == 2
    assert size_opts["M"]["product_count"] == 1

    color_opts = {o["value_key"]: o for o in attrs_by_name["color"]["options"]}
    assert "BLUE" not in color_opts
    assert color_opts["RED"]["product_count"] == 2


def test_available_attributes_excludes_out_of_stock_when_enabled(test_client, shop_with_category_attributes):
    """When enable_stock_on_products is on, products with stock<=0 should not be counted."""
    ids = shop_with_category_attributes

    # Enable stock toggle on the shop
    shop = db.session.query(ShopTable).get(ids["shop_id"])
    shop.config = {"toggles": {"enable_stock_on_products": True}}
    db.session.commit()

    # Set prod3 (size L, color BLUE) to stock=0
    from server.db.models import ProductAttributeValueTable

    prod_with_l = (
        db.session.query(ProductAttributeValueTable.product_id)
        .filter(ProductAttributeValueTable.option_id == ids["size_l_id"])
        .scalar()
    )
    product = db.session.query(ProductTable).get(prod_with_l)
    product.stock = 0
    db.session.commit()

    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{ids['cat1_id']}/available-attributes")
    assert response.status_code == HTTPStatus.OK

    data = response.json()
    attrs_by_name = {a["name"]: a for a in data}

    size_opts = {o["value_key"]: o for o in attrs_by_name["size"]["options"]}
    assert "L" not in size_opts

    color_opts = {o["value_key"]: o for o in attrs_by_name["color"]["options"]}
    assert "BLUE" not in color_opts


def test_available_attributes_includes_out_of_stock_when_toggle_disabled(test_client, shop_with_category_attributes):
    """When enable_stock_on_products is off, products with stock=0 should still be counted."""
    ids = shop_with_category_attributes

    # Set prod3 stock to 0 but don't enable the toggle (shop has no config)
    from server.db.models import ProductAttributeValueTable

    prod_with_l = (
        db.session.query(ProductAttributeValueTable.product_id)
        .filter(ProductAttributeValueTable.option_id == ids["size_l_id"])
        .scalar()
    )
    product = db.session.query(ProductTable).get(prod_with_l)
    product.stock = 0
    db.session.commit()

    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{ids['cat1_id']}/available-attributes")
    assert response.status_code == HTTPStatus.OK

    data = response.json()
    attrs_by_name = {a["name"]: a for a in data}

    # L should still be present since stock toggle is off
    size_opts = {o["value_key"]: o for o in attrs_by_name["size"]["options"]}
    assert "L" in size_opts
    assert size_opts["L"]["product_count"] == 1


def test_available_attributes_nonexistent_category(test_client, shop_with_category_attributes):
    ids = shop_with_category_attributes
    fake_id = uuid4()
    response = test_client.get(f"/shops/{ids['shop_id']}/categories/{fake_id}/available-attributes")
    assert response.status_code == HTTPStatus.NOT_FOUND
