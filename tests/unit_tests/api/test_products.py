from http import HTTPStatus

from server.db.models import ProductTable
from server.utils.json import json_dumps
from tests.unit_tests.factories.product import make_product


def test_products_get_multi(shop_with_products, test_client):
    response = test_client.get(f"/shops/{shop_with_products}/products/")
    assert response.status_code == 200
    products = response.json()
    assert 2 == len(products)


def test_products_get_by_id(shop_with_config, product, test_client):
    response = test_client.get(f"/shops/{shop_with_config}/products/{product}")
    assert response.status_code == 200
    product = response.json()
    assert product["translation"]["main_name"] == "Product for Testing"


def test_products_create(shop, category, test_client):
    body = {
        "shop_id": shop,
        "category_id": category,
        "price": 1.0,
        "tax_category": "vat_zero",
        "max_one": False,
        "shippable": True,
        "featured": False,
        "new_product": False,
        "translation": {
            "main_name": "Create Product Test",
            "main_description": "Update Product Test Description",
            "main_description_short": "Update Product Test Description Short",
            "alt1_name": "",
        },
        "image_1": "",
        "image_2": "",
        "image_3": "",
        "image_4": "",
        "image_5": "",
        "image_6": "",
    }

    response = test_client.post(f"/shops/{shop}/products/", content=json_dumps(body))
    assert HTTPStatus.CREATED == response.status_code, f"No 201 status code: full response {response.json()}"
    product = ProductTable.query.filter_by(id=response.json()["id"]).first()
    assert product.translation.main_name == "Create Product Test"
    assert product.translation.alt1_name == None


def test_products_update(shop_with_config, product, category, test_client):
    body = {
        "shop_id": shop_with_config,
        "category_id": category,
        "price": 1.0,
        "tax_category": "vat_zero",
        "max_one": False,
        "shippable": True,
        "featured": False,
        "new_product": False,
        "translation": {
            "main_name": "Update Product Test",
            "main_description": "Update Product Test Description",
            "main_description_short": "Update Product Test Description Short",
        },
        "image_1": "",
        "image_2": "",
        "image_3": "",
        "image_4": "",
        "image_5": "",
        "image_6": "",
    }

    response = test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body))
    assert response.status_code == 201
    product = ProductTable.query.filter_by(id=product).first()
    assert product.translation.main_name == "Update Product Test"
    assert product.translation.alt1_name == None


def test_products_delete(shop_with_config, product, test_client):
    response = test_client.delete(f"/shops/{shop_with_config}/products/{product}")
    assert response.status_code == 204


def test_products_delete_cascade_cleanup(shop_with_config, product, category, test_client):
    """Test that purging (force=true) a product also deletes its attribute values, but NOT the tags/options."""
    from server.db import db
    from server.db.models import AttributeOptionTable, AttributeTable, ProductAttributeValueTable
    from tests.unit_tests.factories.attribute import make_attribute, make_option, make_pav

    # 1. Setup Test Data
    # Create an attribute and an option
    attr_id = make_attribute(shop_with_config, name="size")
    opt_id = make_option(attr_id, "XL")

    # Create associations
    # Link product to the attribute option
    pav_id = make_pav(product, attr_id, opt_id)

    # Verify setup
    assert db.session.get(ProductAttributeValueTable, pav_id) is not None

    # 2. Perform hard purge (a plain delete only moves to trash and keeps the PAVs)
    response = test_client.delete(f"/shops/{shop_with_config}/products/{product}?force=true")
    assert response.status_code == 204

    # 3. Verify Cascade Deletion
    # These should be gone
    assert db.session.get(ProductTable, product) is None
    assert db.session.get(ProductAttributeValueTable, pav_id) is None

    # These should still exist
    assert db.session.get(AttributeOptionTable, opt_id) is not None
    assert db.session.get(AttributeTable, attr_id) is not None


def test_products_get_multi_with_attributes(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]

    response = test_client.get(f"/shops/{shop_id}/products/with_attributes")
    assert response.status_code == 200
    products = response.json()
    assert len(products) > 0
    assert "product" in products[0]
    assert "attributes" in products[0]

    # Verify that the response contains the expected product ID
    product_ids = {p["product"]["id"] for p in products}
    assert str(ids["product_id"]) in product_ids


def test_products_get_by_id_with_attributes(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    product_id = ids["product_id"]

    response = test_client.get(f"/shops/{shop_id}/products/{product_id}/with_attributes")
    assert response.status_code == 200
    product = response.json()
    assert "product" in product
    assert "attributes" in product
    assert product["product"]["id"] == str(product_id)


def test_products_get_multi_with_attributes_filtered_by_option(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    product_id = ids["product_id"]
    opt1a_id = ids["opt1a_id"]
    attr1_id = ids["attr1_id"]

    # First, we need to create a ProductAttributeValue (PAV) to associate the option with the product
    from tests.unit_tests.factories.attribute import make_pav

    make_pav(product_id, attr1_id, opt1a_id)

    # Filter by option_id
    response = test_client.get(f"/shops/{shop_id}/products/with_attributes?option_id={opt1a_id}")
    assert response.status_code == 200
    products = response.json()
    assert len(products) == 1
    assert products[0]["product"]["id"] == str(product_id)

    # Filter by non-existent option_id should return empty list
    from uuid import uuid4

    response = test_client.get(f"/shops/{shop_id}/products/with_attributes?option_id={uuid4()}")
    assert response.status_code == 200
    assert len(response.json()) == 0


def test_get_products_config_robustness(test_client):
    """Test get_products endpoint with various shop config scenarios."""
    from server.db import db
    from server.db.models import ShopTable
    from tests.unit_tests.factories.categories import make_category
    from tests.unit_tests.factories.product import make_product

    # Helper to create a shop with specific config
    def create_shop_with_config(config_val):
        from uuid import uuid4

        shop = ShopTable(
            name=f"Config Test Shop {uuid4()}",
            config=config_val,
            shop_type="{}",
        )
        db.session.add(shop)
        db.session.commit()
        return shop.id

    # 1. Test with completely empty config "{}" (toggles missing)
    shop_id_1 = create_shop_with_config("{}")
    cat_id_1 = make_category(shop_id=shop_id_1)
    make_product(shop_id=shop_id_1, category_id=cat_id_1)

    response = test_client.get(f"/shops/{shop_id_1}/products/?lang=main")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # 2. Test with toggles present but enable_stock_on_products missing
    shop_id_2 = create_shop_with_config({"toggles": {}})
    cat_id_2 = make_category(shop_id=shop_id_2)
    make_product(shop_id=shop_id_2, category_id=cat_id_2)

    response = test_client.get(f"/shops/{shop_id_2}/products/?lang=main")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # 3. Test with enable_stock_on_products=True
    # (Testing basic robustness only as complex filtering depends on DB state in these tests)
    shop_id_3 = create_shop_with_config({"toggles": {"enable_stock_on_products": True}})
    cat_id_3 = make_category(shop_id=shop_id_3)
    make_product(shop_id=shop_id_3, category_id=cat_id_3)

    response = test_client.get(f"/shops/{shop_id_3}/products/?lang=main")
    assert response.status_code == 200
    assert len(response.json()) == 1

    # 4. Test with string config (should be handled by json.loads)
    import json

    shop_id_4 = create_shop_with_config(json.dumps({"toggles": {"enable_stock_on_products": False}}))
    cat_id_4 = make_category(shop_id=shop_id_4)
    make_product(shop_id=shop_id_4, category_id=cat_id_4)

    response = test_client.get(f"/shops/{shop_id_4}/products/?lang=main")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_products_get_multi_with_attributes_mutually_exclusive_filters(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    opt1a_id = ids["opt1a_id"]
    attr1_id = ids["attr1_id"]

    # Providing both option_id and attribute_id should fail
    response = test_client.get(
        f"/shops/{shop_id}/products/with_attributes?option_id={opt1a_id}&attribute_id={attr1_id}"
    )
    assert response.status_code == 400
    assert "Only one filter may be used at a time" in response.json()["detail"]["message"]


def test_products_get_multi_filter_in_stock(shop, category, test_client):
    in_id = make_product(shop_id=shop, category_id=category, main_name="HasStock", stock=5)
    out_id = make_product(shop_id=shop, category_id=category, main_name="NoStock", stock=0)

    response = test_client.get(f"/shops/{shop}/products/?stock_status=in_stock")
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()}
    assert str(in_id) in ids
    assert str(out_id) not in ids


def test_products_get_multi_filter_out_of_stock(shop, category, test_client):
    in_id = make_product(shop_id=shop, category_id=category, main_name="HasStock", stock=5)
    out_id = make_product(shop_id=shop, category_id=category, main_name="NoStock", stock=0)

    response = test_client.get(f"/shops/{shop}/products/?stock_status=out_of_stock")
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()}
    assert str(out_id) in ids
    assert str(in_id) not in ids


def test_products_get_multi_filter_all_is_default(shop, category, test_client):
    make_product(shop_id=shop, category_id=category, main_name="HasStock", stock=5)
    make_product(shop_id=shop, category_id=category, main_name="NoStock", stock=0)

    default_response = test_client.get(f"/shops/{shop}/products/")
    explicit_response = test_client.get(f"/shops/{shop}/products/?stock_status=all")
    assert default_response.status_code == 200
    assert explicit_response.status_code == 200
    assert len(default_response.json()) == 2
    assert {p["id"] for p in default_response.json()} == {p["id"] for p in explicit_response.json()}


def test_products_get_multi_filter_invalid_stock_status(shop, test_client):
    response = test_client.get(f"/shops/{shop}/products/?stock_status=bogus")
    assert response.status_code == 422


def test_products_get_multi_with_attributes_filter_out_of_stock(shop, category, test_client):
    in_id = make_product(shop_id=shop, category_id=category, main_name="HasStock", stock=5)
    out_id = make_product(shop_id=shop, category_id=category, main_name="NoStock", stock=0)

    response = test_client.get(f"/shops/{shop}/products/with_attributes?stock_status=out_of_stock")
    assert response.status_code == 200
    ids = {p["product"]["id"] for p in response.json()}
    assert str(out_id) in ids
    assert str(in_id) not in ids


def _product_body(shop_id, category_id, name="Test Product", sku=None):
    body = {
        "shop_id": str(shop_id),
        "category_id": str(category_id),
        "price": 1.0,
        "tax_category": "vat_zero",
        "max_one": False,
        "shippable": True,
        "featured": False,
        "new_product": False,
        "translation": {
            "main_name": name,
            "main_description": "desc",
            "main_description_short": "short",
        },
        "image_1": "",
        "image_2": "",
        "image_3": "",
        "image_4": "",
        "image_5": "",
        "image_6": "",
    }
    if sku is not None:
        body["sku"] = sku
    return body


def test_product_create_sets_short_id(shop, category, test_client):
    response = test_client.post(f"/shops/{shop}/products/", content=json_dumps(_product_body(shop, category)))
    assert response.status_code == HTTPStatus.CREATED
    product = ProductTable.query.filter_by(id=response.json()["id"]).first()
    assert product.short_id is not None
    assert len(product.short_id) == 12


def test_product_create_with_sku(shop, category, test_client):
    response = test_client.post(
        f"/shops/{shop}/products/", content=json_dumps(_product_body(shop, category, sku="TST-001"))
    )
    assert response.status_code == HTTPStatus.CREATED
    product = ProductTable.query.filter_by(id=response.json()["id"]).first()
    assert product.sku == "TST-001"


def test_product_update_sets_sku(shop_with_config, product, category, test_client):
    body = _product_body(shop_with_config, category, sku="UPD-999")
    response = test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body))
    assert response.status_code == 201
    updated = ProductTable.query.filter_by(id=product).first()
    assert updated.sku == "UPD-999"


def test_product_duplicate_sku_same_shop_rejected(shop, category, test_client):
    test_client.post(f"/shops/{shop}/products/", content=json_dumps(_product_body(shop, category, sku="DUP-001")))
    response = test_client.post(
        f"/shops/{shop}/products/", content=json_dumps(_product_body(shop, category, name="Other", sku="DUP-001"))
    )
    assert response.status_code == HTTPStatus.CONFLICT


def test_product_duplicate_sku_different_shop_allowed(shop, category, test_client):
    from tests.unit_tests.factories.categories import make_category
    from tests.unit_tests.factories.shop import make_shop

    shop2 = make_shop(with_config=False, random_shop_name=True)
    category2 = make_category(shop_id=shop2)
    test_client.post(f"/shops/{shop}/products/", content=json_dumps(_product_body(shop, category, sku="XSH-001")))
    response = test_client.post(
        f"/shops/{shop2}/products/", content=json_dumps(_product_body(shop2, category2, sku="XSH-001"))
    )
    assert response.status_code == HTTPStatus.CREATED


def test_force_unique_names_rejects_duplicate(shop_with_config, category, test_client):
    # Enable the toggle via config update
    from server.db import ShopTable

    shop = ShopTable.query.filter_by(id=shop_with_config).first()
    import copy
    import json

    from sqlalchemy.orm.attributes import flag_modified

    config = json.loads(shop.config) if isinstance(shop.config, str) else copy.deepcopy(shop.config)
    config["toggles"]["force_unique_product_names"] = True
    shop.config = config
    flag_modified(shop, "config")
    from server.db import db

    db.session.commit()

    test_client.post(
        f"/shops/{shop_with_config}/products/",
        content=json_dumps(_product_body(shop_with_config, category, name="Unique Name")),
    )
    response = test_client.post(
        f"/shops/{shop_with_config}/products/",
        content=json_dumps(_product_body(shop_with_config, category, name="Unique Name")),
    )
    assert response.status_code == HTTPStatus.CONFLICT


def test_force_unique_names_off_allows_duplicate(shop_with_config, category, test_client):
    test_client.post(
        f"/shops/{shop_with_config}/products/",
        content=json_dumps(_product_body(shop_with_config, category, name="Shared Name")),
    )
    response = test_client.post(
        f"/shops/{shop_with_config}/products/",
        content=json_dumps(_product_body(shop_with_config, category, name="Shared Name")),
    )
    assert response.status_code == HTTPStatus.CREATED
