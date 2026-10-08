import json
from http import HTTPStatus

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


def test_my_shops_admin_gets_all_shops(test_client, shop):
    response = test_client.get("/shops/my-shops")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["is_admin"] is True
    assert data["can_write"] is True
    assert len(data["shops"]) == 2


def test_shop_get_by_id(shop, test_client):
    response = test_client.get(f"/shops/{shop}")
    assert HTTPStatus.OK == response.status_code
    shop = response.json()
    assert shop["name"] == "Test Shop"


def test_shop_with_categories(shop_with_categories):
    shop = ShopTable.query.filter_by(id=shop_with_categories).first()
    assert len(shop.shop_to_category) == 2


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
    response = test_client.post("/shops", content=json_dumps(body))
    assert HTTPStatus.CREATED == response.status_code, f"No 201 status code: full response {response.json()}"
    item = ShopTable.query.filter_by(id=response.json()["id"]).first()
    assert item.name == "Test Shop"
    assert item.description == "Test Shop Description"


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
                "force_unique_product_names": False,
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

    response = test_client.put(f"/shops/config/{shop}", content=json.dumps(body))
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
                "force_unique_product_names": False,
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
    response = test_client.put(f"/shops/config/{shop_with_config}", content=json_dumps(body))
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
                "force_unique_product_names": False,
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
    response = test_client.put(f"/shops/config/{shop_with_config}", content=json_dumps(body))
    assert 201 == response.status_code
    config = response.json()
    assert config["config"]["shipping"]["enabled"] is True
    assert config["config"]["shipping"]["method"] == "fixed"
    assert config["config"]["shipping"]["fixed_fee"] == 4.95
    assert config["config"]["shipping"]["free_shipping_above_amount"] == 50.0


def test_shop_delete_success(test_client):
    from tests.unit_tests.factories.shop import make_shop

    shop_id = make_shop(random_shop_name=True)
    response = test_client.delete(f"/shops/{shop_id}")
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert ShopTable.query.filter_by(id=shop_id).first() is None


def test_shop_delete_not_found(test_client):
    from uuid import uuid4

    random_id = uuid4()
    response = test_client.delete(f"/shops/{random_id}")
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_shop_delete_cascades_owned_data(test_client):
    from server.db import db
    from server.db.models import (
        Account,
        AttributeTable,
        CategoryTable,
        FaqTable,
        OrderTable,
        ProductTable,
        ShopTable,
        TagTable,
    )
    from tests.unit_tests.factories.categories import make_category
    from tests.unit_tests.factories.product import make_product
    from tests.unit_tests.factories.shop import make_shop
    from tests.unit_tests.factories.tag import make_tag

    # Create Shop A with related entities
    shop_a_id = make_shop(random_shop_name=True)

    account_a = Account(shop_id=shop_a_id, name="Customer A")
    db.session.add(account_a)
    db.session.flush()

    order_a = OrderTable(shop_id=shop_a_id, account_id=account_a.id, total=100.00)
    db.session.add(order_a)

    attr_a = AttributeTable(shop_id=shop_a_id, name="Color")
    db.session.add(attr_a)

    # Create Shop B with related entities
    shop_b_id = make_shop(random_shop_name=True)
    cat_b = make_category(shop_b_id)
    tag_b = make_tag(shop_b_id)
    prod_b = make_product(shop_b_id, cat_b)

    # Create shared/global data
    faq = FaqTable(question="What is this?", answer="A platform.", category="General")
    db.session.add(faq)

    db.session.commit()

    # Delete Shop A
    response = test_client.delete(f"/shops/{shop_a_id}")
    assert response.status_code == HTTPStatus.NO_CONTENT

    # Verify Shop A and its owned data are deleted
    assert ShopTable.query.filter_by(id=shop_a_id).first() is None
    assert CategoryTable.query.filter_by(shop_id=shop_a_id).first() is None
    assert TagTable.query.filter_by(shop_id=shop_a_id).first() is None
    assert ProductTable.query.filter_by(shop_id=shop_a_id).first() is None
    assert Account.query.filter_by(shop_id=shop_a_id).first() is None
    assert OrderTable.query.filter_by(shop_id=shop_a_id).first() is None
    assert AttributeTable.query.filter_by(shop_id=shop_a_id).first() is None

    # Verify Shop B data remains untouched
    assert ShopTable.query.filter_by(id=shop_b_id).first() is not None
    assert CategoryTable.query.filter_by(id=cat_b).first() is not None
    assert TagTable.query.filter_by(id=tag_b).first() is not None
    assert ProductTable.query.filter_by(id=prod_b).first() is not None

    # Verify global data remains untouched
    assert FaqTable.query.filter_by(id=faq.id).first() is not None


def test_shop_delete_non_fk_integrity_error_reraised(test_client, monkeypatch):
    from unittest.mock import MagicMock

    from sqlalchemy.exc import IntegrityError

    from server.crud.crud_shop import shop_crud

    # Simulate a non-FK IntegrityError (e.g. check violation pgcode 23514)
    orig_mock = MagicMock()
    orig_mock.pgcode = "23514"
    exc = IntegrityError("CHECK VIOLATION", params=None, orig=orig_mock)

    def mock_delete(*args, **kwargs):
        raise exc

    monkeypatch.setattr(shop_crud, "delete", mock_delete)

    from tests.unit_tests.factories.shop import make_shop

    shop_id = make_shop(random_shop_name=True)

    try:
        response = test_client.delete(f"/shops/{shop_id}")
        assert response.status_code == 500
    except IntegrityError:
        # Re-raised as expected when unhandled by FastAPI exception handlers in test mode
        pass
