import json
from http import HTTPStatus

from more_itertools import one

from server.db import ShopTable
from server.utils.json import json_dumps


def test_shops_get_multi(test_client, shop):
    # todo: implement correct shop and shops fixtures
    response = test_client.get("/shops")
    assert response.status_code == 200
    shops = response.json()
    assert 2 == len(shops)  # 2 shops, one from the fixture, one "Default shop" from the migrations
    assert "Default shop" in [shop["description"] for shop in shops]
    assert "Test Shop" in [shop["name"] for shop in shops]


def test_shop_get_by_id(shop, test_client):
    response = test_client.get(f"/shops/{shop}")
    assert HTTPStatus.OK == response.status_code
    shop = response.json()
    assert shop["name"] == "Test Shop"


def test_shop_with_categories(shop_with_categories):
    shop = ShopTable.query.filter_by(id=shop_with_categories).first()
    assert len(shop.shop_to_category) == 2


#
#
# def test_shop_save(test_client, superuser_token_headers):
#     body = {"name": "New Test Shop", "description": "New Test Shop description"}
#
#     response = test_client.post("/api/shop_endpoints/", data=json_dumps(body), headers=superuser_token_headers)
#     assert HTTPStatus.CREATED == response.status_code
#     shops = test_client.get("/api/shop_endpoints").json()
#     assert 1 == len(shops)
#
#
# def test_shop_update(shop_1, test_client, superuser_token_headers):
#     body = {"name": "Updated Shop", "description": "Shop description"}
#     response = test_client.put(
#         f"/api/shop_endpoints/{shop_1.id}", data=json_dumps(body), headers=superuser_token_headers
#     )
#     assert HTTPStatus.CREATED == response.status_code
#
#     response_updated = test_client.get(f"/api/shop_endpoints/{shop_1.id}", headers=superuser_token_headers)
#     shop = response_updated.json()
#     assert shop["name"] == "Updated Shop"


def test_shop_create(test_client):
    body = {
        "name": "Test Shop",
        "description": "Test Shop Description",
        "vat_standard": 21,
        "vat_lower_1": 10,
        "vat_lower_2": 5,
        "vat_lower_3": 2,
        "vat_special": 12,
        "vat_zero": 0,
    }
    response = test_client.post("/shops", data=json_dumps(body))
    assert HTTPStatus.CREATED == response.status_code, f"No 201 status code: full response {response.json()}"
    item = ShopTable.query.filter_by(id=response.json()["id"]).first()
    assert item.name == "Test Shop"
    assert item.description == "Test Shop Description"


# def test_shop_delete(shop_1, test_client, superuser_token_headers):
#     response = test_client.delete(f"/api/shop_endpoints/{shop_1.id}", headers=superuser_token_headers)
#     assert HTTPStatus.NO_CONTENT == response.status_code
#     shops = test_client.get("/api/shop_endpoints", headers=superuser_token_headers).json()
#     assert len(shops) == 1  # Changed to 1 because admin has 2 shop_endpoints now


# def test_shop_get_config(test_client, shop_with_config):
#     response = test_client.get(f"/shops/config/{shop_with_config}")
#     assert 200 == response.status_code
# config = response.json()
# expected_config = {
#     "config": {
#         "short_shop_name": "string",
#         "main_banner": "string",
#         "alt1_banner": "string",
#         "alt2_banner": "string",
#         "languages": {
#             "main": {
#                 "language_name": "string",
#                 "menu_items": {
#                     "about": "string",
#                     "cart": "string",
#                     "checkout": "string",
#                     "products": "string",
#                     "contact": "string",
#                     "policies": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                     "website": "string",
#                     "phone": "string",
#                     "email": "string",
#                     "address": "string",
#                 },
#                 "static_texts": {
#                     "about": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                 },
#             },
#             "alt1": {
#                 "language_name": "string",
#                 "menu_items": {
#                     "about": "string",
#                     "cart": "string",
#                     "checkout": "string",
#                     "products": "string",
#                     "contact": "string",
#                     "policies": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                     "website": "string",
#                     "phone": "string",
#                     "email": "string",
#                     "address": "string",
#                 },
#                 "static_texts": {
#                     "about": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                 },
#             },
#             "alt2": {
#                 "language_name": "string",
#                 "menu_items": {
#                     "about": "string",
#                     "cart": "string",
#                     "checkout": "string",
#                     "products": "string",
#                     "contact": "string",
#                     "policies": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                     "website": "string",
#                     "phone": "string",
#                     "email": "string",
#                     "address": "string",
#                 },
#                 "static_texts": {
#                     "about": "string",
#                     "terms": "string",
#                     "privacy_policy": "string",
#                     "return_policy": "string",
#                 },
#             },
#         },
#         "contact": {
#             "company": "string",
#             "website": "https://example.com/",
#             "phone": "+31 6 12345678",
#             "email": "user@example.com",
#             "address": "string",
#             "twitter": "https://example.com/",
#             "facebook": "https://example.com/",
#             "instagram": "https://example.com/",
#         },
#     },
#     "config_version": 0,
#     "stripe_public_key": "string",
# }
# assert config == expected_config


def test_shop_create_config(test_client, shop):
    body = {
        "config": {
            "short_shop_name": "string",
            "main_banner": "string",
            "alt1_banner": "string",
            "alt2_banner": "string",
            "google_analytics_id": "string",
            "gradient_percentage": 0,
            "logo": "string",
            "languages": {
                "main": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
                "alt1": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
                "alt2": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
            },
            "contact": {
                "company": "string",
                "website": "https://example.com/",
                "phone": "+31 6 12345678",
                "email": "user@example.com",
                "address": "string",
                "zip_code": "string",
                "city": "string",
                "twitter": "https://example.com/",
                "facebook": "https://example.com/",
                "instagram": "https://example.com/",
                "linkedin": "https://example.com/",
                "tiktok": "https://example.com/",
            },
            "toggles": {
                "show_new_products": True,
                "show_featured_products": True,
                "show_categories": True,
                "show_shop_name": True,
                "show_nav_categories": False,
                "language_alt1_enabled": False,
                "language_alt2_enabled": False,
                "product_call_to_action_enabled": False,
                "enable_stock_on_products": True,
                "enable_attributes_for_categories": False,
            },
            "legal": {
                "kvk_number": "string",
                "btw_number": "string",
            },
            "shipping": None,
            "order_status_mails": None,
        },
        "config_version": 0,
    }

    response = test_client.put(f"/shops/config/{shop}", data=json.dumps(body))
    assert 201 == response.status_code
    config = response.json()
    assert config == body


def test_shop_update_config(test_client, shop_with_config):
    body = {
        "config": {
            "short_shop_name": "Test",
            "main_banner": "string",
            "alt1_banner": "string",
            "alt2_banner": "string",
            "google_analytics_id": "string",
            "gradient_percentage": 0,
            "logo": "string",
            "languages": {
                "main": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
                "alt1": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
                "alt2": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
            },
            "contact": {
                "company": "string",
                "website": "https://example.com/",
                "phone": "+31 6 12345678",
                "email": "user@example.com",
                "address": "string",
                "zip_code": "string",
                "city": "string",
                "twitter": "https://example.com/",
                "facebook": "https://example.com/",
                "instagram": "https://example.com/",
                "linkedin": "https://example.com/",
                "tiktok": "https://example.com/",
            },
            "toggles": {
                "show_new_products": True,
                "show_featured_products": True,
                "show_categories": True,
                "show_shop_name": True,
                "show_nav_categories": False,
                "language_alt1_enabled": False,
                "language_alt2_enabled": False,
                "product_call_to_action_enabled": False,
                "enable_stock_on_products": True,
                "enable_attributes_for_categories": False,
            },
            "legal": {
                "kvk_number": "string",
                "btw_number": "string",
            },
            "shipping": None,
            "order_status_mails": None,
        },
        "config_version": 0,
    }
    response = test_client.put(f"/shops/config/{shop_with_config}", data=json_dumps(body))
    assert 201 == response.status_code
    config = response.json()
    assert config == body


def test_shop_update_config_with_shipping(test_client, shop_with_config):
    body = {
        "config": {
            "short_shop_name": "Test",
            "main_banner": "string",
            "alt1_banner": "string",
            "alt2_banner": "string",
            "google_analytics_id": "string",
            "gradient_percentage": 0,
            "logo": "string",
            "languages": {
                "main": {
                    "language_name": "string",
                    "menu_items": {
                        "about": "string",
                        "cart": "string",
                        "checkout": "string",
                        "products": "string",
                        "contact": "string",
                        "policies": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                        "website": "string",
                        "phone": "string",
                        "email": "string",
                        "address": "string",
                    },
                    "static_texts": {
                        "about": "string",
                        "terms": "string",
                        "privacy_policy": "string",
                        "return_policy": "string",
                    },
                },
            },
            "contact": {
                "company": "string",
                "phone": "+31 6 12345678",
                "email": "user@example.com",
                "address": "string",
                "zip_code": "string",
                "city": "string",
            },
            "toggles": {
                "show_new_products": True,
                "show_featured_products": True,
                "show_categories": True,
                "show_shop_name": True,
                "show_nav_categories": False,
                "language_alt1_enabled": False,
                "language_alt2_enabled": False,
                "product_call_to_action_enabled": False,
                "enable_stock_on_products": True,
                "enable_attributes_for_categories": False,
            },
            "legal": None,
            "shipping": {
                "enabled": True,
                "method": "fixed",
                "fixed_fee": 4.95,
                "free_shipping_above_enabled": True,
                "free_shipping_above_amount": 50.0,
            },
        },
        "config_version": 1,
    }
    response = test_client.put(f"/shops/config/{shop_with_config}", data=json_dumps(body))
    assert 201 == response.status_code
    config = response.json()
    assert config["config"]["shipping"]["enabled"] is True
    assert config["config"]["shipping"]["method"] == "fixed"
    assert config["config"]["shipping"]["fixed_fee"] == 4.95
    assert config["config"]["shipping"]["free_shipping_above_amount"] == 50.0
