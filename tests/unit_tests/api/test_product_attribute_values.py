from uuid import uuid4

from server.db import db
from server.db.models import ProductAttributeValueTable
from server.utils.json import json_dumps
from tests.unit_tests.factories.attribute import make_pav


def test_list_product_attribute_values_scoped_by_shop(
    test_client, shop_with_products_and_attributes, other_shop_product
):
    ids = shop_with_products_and_attributes

    # Seed: in main shop, add one PAV and remember its id
    pav1_id = make_pav(ids["product_id"], ids["attr1_id"], ids["opt1a_id"])  # main shop PAV

    # Seed a PAV in the other shop (should not appear in the list for main shop)
    make_pav(other_shop_product, ids["other_attr_id"], ids["other_opt_id"])  # should not appear in list

    resp = test_client.get(f"/shops/{ids['shop_id']}/product-attribute-values/")
    assert resp.status_code == 200
    items = resp.json()
    # Only PAVs for products in the main shop should be returned (we created 1 such PAV above)
    assert len(items) == 1

    # Check response item matches the created PAV values
    item = items[0]
    assert item["id"] == str(pav1_id)
    assert item["product_id"] == str(ids["product_id"])
    assert item["attribute_id"] == str(ids["attr1_id"])
    assert item["option_id"] == str(ids["opt1a_id"])


def test_get_product_attribute_value_by_id_and_scoping(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    pav_id = make_pav(ids["product_id"], ids["attr1_id"], ids["opt1a_id"])

    # Correct shop returns the PAV
    resp_ok = test_client.get(f"/shops/{ids['shop_id']}/product-attribute-values/{pav_id}")
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["id"] == str(pav_id)

    # Wrong shop should 404
    resp_404 = test_client.get(f"/shops/{ids['other_shop_id']}/product-attribute-values/{pav_id}")
    assert resp_404.status_code == 404

    # Non-existent id should 404
    resp_404b = test_client.get(f"/shops/{ids['shop_id']}/product-attribute-values/{uuid4()}")
    assert resp_404b.status_code == 404


def test_post_create_product_attribute_values_for_product(
    test_client, shop_with_products_and_attributes, other_shop_product
):
    ids = shop_with_products_and_attributes

    body = {"option_ids": [str(ids["opt1b_id"])]}
    resp = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body),
    )
    assert resp.status_code == 201

    # Verify created
    pavs = (
        db.session.query(ProductAttributeValueTable)
        .filter(
            ProductAttributeValueTable.product_id == ids["product_id"],
            ProductAttributeValueTable.attribute_id == ids["attr1_id"],
            ProductAttributeValueTable.option_id == ids["opt1b_id"],
        )
        .all()
    )
    assert len(pavs) == 1

    # 404 when product does not belong to shop
    resp_bad_shop = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{other_shop_product}",
        content=json_dumps(body),
    )
    assert resp_bad_shop.status_code == 404

    # 400 when option id does not exist
    body_invalid = {"option_ids": [str(uuid4())]}
    resp_invalid = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body_invalid),
    )
    assert resp_invalid.status_code == 400


def test_put_selected_product_attribute_values_grouping_and_validations(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes

    # Seed existing: attr1: opt1a, attr2: opt2a
    pav_a1 = make_pav(ids["product_id"], ids["attr1_id"], ids["opt1a_id"])  # noqa: F841
    pav_a2 = make_pav(ids["product_id"], ids["attr2_id"], ids["opt2a_id"])  # noqa: F841

    # Update: only submit opt1b (same attr1). This should replace attr1's selection
    # and keep attr2 entries untouched (since attr2 isn't part of inferred attributes here).
    body = {"option_ids": [str(ids["opt1b_id"])]}
    resp = test_client.put(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body),
    )
    assert resp.status_code == 204

    # Verify attr1 has only opt1b
    pavs_attr1 = (
        db.session.query(ProductAttributeValueTable)
        .filter(
            ProductAttributeValueTable.product_id == ids["product_id"],
            ProductAttributeValueTable.attribute_id == ids["attr1_id"],
        )
        .all()
    )
    assert {row.option_id for row in pavs_attr1} == {ids["opt1b_id"]}

    # Verify attr2 unchanged (still opt2a)
    pavs_attr2 = (
        db.session.query(ProductAttributeValueTable)
        .filter(
            ProductAttributeValueTable.product_id == ids["product_id"],
            ProductAttributeValueTable.attribute_id == ids["attr2_id"],
        )
        .all()
    )
    assert {row.option_id for row in pavs_attr2} == {ids["opt2a_id"]}

    # 400 when empty list
    resp_empty = test_client.put(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps({"option_ids": []}),
    )
    assert resp_empty.status_code == 400

    # 400 when any option id invalid
    resp_invalid = test_client.put(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps({"option_ids": [str(uuid4()), str(ids["opt1b_id"])]}),
    )
    assert resp_invalid.status_code == 400

    # 400 when inferred attribute is from another shop
    resp_wrong_attr_shop = test_client.put(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps({"option_ids": [str(ids["other_opt_id"])]}),
    )
    assert resp_wrong_attr_shop.status_code == 400


def test_delete_product_attribute_value(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    pav_id = make_pav(ids["product_id"], ids["attr1_id"], ids["opt1a_id"])

    # Valid delete
    resp = test_client.delete(f"/shops/{ids['shop_id']}/product-attribute-values/{pav_id}")
    assert resp.status_code == 204

    # Deleting again should 404
    resp_again = test_client.delete(f"/shops/{ids['shop_id']}/product-attribute-values/{pav_id}")
    assert resp_again.status_code == 404

    # Create another pav and try deleting with wrong shop -> 404
    pav_id2 = make_pav(ids["product_id"], ids["attr1_id"], ids["opt1b_id"])  # noqa: F841
    resp_wrong_shop = test_client.delete(f"/shops/{ids['other_shop_id']}/product-attribute-values/{pav_id2}")
    assert resp_wrong_shop.status_code == 404
