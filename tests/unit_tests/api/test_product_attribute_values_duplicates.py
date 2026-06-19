from server.db.models import ProductAttributeValueTable
from server.utils.json import json_dumps


def test_post_create_product_attribute_values_for_product_duplicate_conflict(
    test_client, shop_with_products_and_attributes
):
    ids = shop_with_products_and_attributes

    body = {"option_ids": [str(ids["opt1a_id"])]}

    # First creation should succeed
    resp1 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body),
    )
    assert resp1.status_code == 201

    # Verify 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1

    # Second, identical creation doesn't care, it doesn't actually make new one and just returns 201
    resp2 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body),
    )
    assert resp2.status_code == 201

    # Verify still only 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1


def test_post_deprecated_create_product_attribute_value_duplicate_conflict(
    test_client, shop_with_products_and_attributes
):
    ids = shop_with_products_and_attributes

    # First create via deprecated endpoint
    body = {
        "product_id": str(ids["product_id"]),
        "attribute_id": str(ids["attr1_id"]),
        "option_id": str(ids["opt1a_id"]),
    }
    resp1 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/",
        content=json_dumps(body),
    )
    assert resp1.status_code == 201

    # Verify 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1

    # Duplicate via the same endpoint should return 409
    resp2 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/",
        content=json_dumps(body),
    )
    assert resp2.status_code == 409

    # Verify still only 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1


def test_cross_endpoint_create_new_then_deprecated(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes

    # 1. Create via new endpoint
    body_new = {"option_ids": [str(ids["opt1a_id"])]}
    resp1 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body_new),
    )
    assert resp1.status_code == 201

    # 2. Try to create same via deprecated endpoint -> should 409
    body_depr = {
        "product_id": str(ids["product_id"]),
        "attribute_id": str(ids["attr1_id"]),
        "option_id": str(ids["opt1a_id"]),
    }
    resp2 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/",
        content=json_dumps(body_depr),
    )
    assert resp2.status_code == 409

    # Verify only 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1


def test_cross_endpoint_create_deprecated_then_new(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes

    # 1. Create via deprecated endpoint
    body_depr = {
        "product_id": str(ids["product_id"]),
        "attribute_id": str(ids["attr1_id"]),
        "option_id": str(ids["opt1a_id"]),
    }
    resp1 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/",
        content=json_dumps(body_depr),
    )
    assert resp1.status_code == 201

    # 2. Try to create same via new endpoint -> should 201 (idempotent-like)
    body_new = {"option_ids": [str(ids["opt1a_id"])]}
    resp2 = test_client.post(
        f"/shops/{ids['shop_id']}/product-attribute-values/{ids['product_id']}",
        content=json_dumps(body_new),
    )
    assert resp2.status_code == 201

    # Verify only 1 record in DB
    count = ProductAttributeValueTable.query.count()
    assert count == 1
