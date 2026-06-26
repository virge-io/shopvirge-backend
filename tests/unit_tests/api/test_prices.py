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
