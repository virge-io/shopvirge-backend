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
