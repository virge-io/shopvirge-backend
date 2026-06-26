from server.db.models import CategoryTable
from server.utils.json import json_dumps


def test_categories_get_multi(shop_with_categories, test_client):
    response = test_client.get(f"/shops/{shop_with_categories}/categories/")
    assert response.status_code == 200
    categories = response.json()
    assert 2 == len(categories)


def test_categories_get_by_id(shop, category, test_client):
    response = test_client.get(f"/shops/{shop}/categories/{category}")
    assert response.status_code == 200
    category = response.json()
    assert category["translation"]["main_name"] == "Main name"


def test_categories_create(shop, test_client):
    body = {
        "shop_id": shop,
        "color": "#FFFFFF",
        "translation": {
            "main_name": "Create Category Test",
            "main_description": "Create Category Test Description",
            "alt1_name": "",
        },
        "main_image": "",
        "alt1_image": "",
        "alt2_image": "",
    }

    response = test_client.post(f"/shops/{shop}/categories/", content=json_dumps(body))
    assert response.status_code == 201
    category = CategoryTable.query.filter_by(id=response.json()["id"]).first()
    assert category.translation.main_name == "Create Category Test"
    assert category.translation.alt1_name == None


def test_categories_update(shop, category, test_client):
    body = {
        "shop_id": shop,
        "color": "#FFFFFF",
        "translation": {
            "main_name": "Update Category Test",
            "main_description": "Update Category Test Description",
            "alt1_name": "",
        },
        "main_image": "",
        "alt1_image": "",
        "alt2_image": "",
    }

    response = test_client.put(f"/shops/{shop}/categories/{category}", content=json_dumps(body))
    assert response.status_code == 201
    category = CategoryTable.query.filter_by(id=category).first()
    assert category.translation.main_name == "Update Category Test"
    assert category.translation.alt1_name == None


def test_categories_delete(shop, category, test_client):
    response = test_client.delete(f"/shops/{shop}/categories/{category}")
    assert response.status_code == 204
