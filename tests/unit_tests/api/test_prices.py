from server.utils.json import json_dumps


def test_prices_get_multi(shop_with_config, product, test_client):
    response = test_client.get(f"/shops/{shop_with_config}/prices/?lang=main")
    assert response.status_code == 200
    prices = response.json()
    assert 1 == len(prices)


def test_prices_get_multi_untranslated(
    shop_with_config, product, product_translated, product_translated_category_untranslated, test_client
):
    response = test_client.get(f"/shops/{shop_with_config}/prices/?lang=alt1")
    assert response.status_code == 200
    prices = response.json()
    # should be 1 with a Dutch name, since 1 out of 3 products is fully translated
    assert 1 == len(prices)
    assert prices[0]["name"] == "Product voor Testen"


def test_cart_prices_get_multi(shop_with_config, product, test_client):
    body = {"products": [product]}

    response = test_client.post(f"/shops/{shop_with_config}/prices/?lang=main", content=json_dumps(body))
    assert response.status_code == 200
    prices = response.json()
    assert 1 == len(prices)


def test_cart_prices_get_multi_untranslated(shop_with_config, product, product_translated, test_client):
    body = {"products": [product, product_translated]}

    response = test_client.post(f"/shops/{shop_with_config}/prices/?lang=alt1", content=json_dumps(body))
    assert response.status_code == 200
    prices = response.json()
    # should be 2, but one should be English, the other Dutch
    assert 2 == len(prices)
    assert prices[0]["name"] == "Product for Testing"
    assert prices[1]["name"] == "Product voor Testen"


# from http import HTTPStatus
# from uuid import uuid4
#
# import structlog
#
# from server.utils.json import json_dumps
#
# logger = structlog.getLogger(__name__)
#
#
# def test_prices_get_multi(price_1, price_2, price_3, test_client, superuser_token_headers):
#     response = test_client.get("/api/prices", headers=superuser_token_headers)
#
#     assert HTTPStatus.OK == response.status_code
#     prices = response.json()
#
#     assert 3 == len(prices)
#
#
# def test_price_get_by_id(price_1, test_client, superuser_token_headers):
#     response = test_client.get(f"/api/prices/{price_1.id}", headers=superuser_token_headers)
#     print(response.__dict__)
#     assert HTTPStatus.OK == response.status_code
#     price = response.json()
#     assert price["half"] == 5.50
#
#
# def test_price_get_by_id_404(price_1, test_client, superuser_token_headers):
#     response = test_client.get(f"/api/prices/{str(uuid4())}", headers=superuser_token_headers)
#     assert HTTPStatus.NOT_FOUND == response.status_code
#
#
# def test_price_save(test_client, superuser_token_headers):
#     body = {"internal_product_id": "101", "half": 5.50, "one": 10.0, "five": 45.0, "joint": 4.50}
#     response = test_client.post("/api/prices/", content=json_dumps(body), headers=superuser_token_headers)
#     assert HTTPStatus.CREATED == response.status_code
#     prices = test_client.get("/api/prices", headers=superuser_token_headers).json()
#     assert 1 == len(prices)
#
#
# def test_price_update(price_1, test_client, superuser_token_headers):
#     body = {"internal_product_id": "01", "half": 6.50, "one": 10.0, "five": 45.0, "joint": 4.50}
#     response = test_client.put(f"/api/prices/{price_1.id}", content=json_dumps(body), headers=superuser_token_headers)
#     assert HTTPStatus.CREATED == response.status_code
#
#     response_updated = test_client.get(f"/api/prices/{price_1.id}", headers=superuser_token_headers)
#     price = response_updated.json()
#     assert price["half"] == 6.50
#
#
# def test_price_delete(price_1, test_client, superuser_token_headers):
#     response = test_client.delete(f"/api/prices/{price_1.id}", headers=superuser_token_headers)
#     assert HTTPStatus.NO_CONTENT == response.status_code
#     prices = test_client.get("/api/prices", headers=superuser_token_headers).json()
#     assert 0 == len(prices)
