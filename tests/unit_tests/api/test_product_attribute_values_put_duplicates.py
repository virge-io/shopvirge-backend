from server.db import db
from server.db.models import ProductAttributeValueTable
from server.utils.json import json_dumps


def test_put_product_attribute_values_with_duplicate_option_ids(test_client, shop_with_products_and_attributes):
    """
    Test that sending duplicate option_ids in the PUT endpoint is handled gracefully.
    The endpoint should deduplicate them using a set and only create one record per unique option.
    """
    ids = shop_with_products_and_attributes
    product_id = ids["product_id"]
    shop_id = ids["shop_id"]
    option_id = str(ids["opt1a_id"])

    # Request body with duplicate option_ids
    body = {"option_ids": [option_id, option_id]}

    # PUT request should succeed with 404 No Content
    resp = test_client.put(
        f"/shops/{shop_id}/product-attribute-values/{product_id}",
        content=json_dumps(body),
    )
    assert resp.status_code == 400


def test_put_product_attribute_values_with_duplicates_and_pre_existing_data(
    test_client, shop_with_products_and_attributes
):
    """
    Test PUT with duplicates when some of the options already exist in the database.
    It should still handle it correctly and not try to re-create existing ones (idempotency).
    """
    ids = shop_with_products_and_attributes
    product_id = ids["product_id"]
    shop_id = ids["shop_id"]
    opt1a = str(ids["opt1a_id"])
    opt1b = str(ids["opt1b_id"])

    # 1. First, create one option normally
    test_client.put(
        f"/shops/{shop_id}/product-attribute-values/{product_id}",
        content=json_dumps({"option_ids": [opt1a]}),
    )

    # 2. Now PUT with opt1a (pre-existing) and opt1b (new), but with duplicates in the list
    body = {"option_ids": [opt1a, opt1b, opt1a, opt1b]}
    resp = test_client.put(
        f"/shops/{shop_id}/product-attribute-values/{product_id}",
        content=json_dumps(body),
    )
    assert resp.status_code == 400
