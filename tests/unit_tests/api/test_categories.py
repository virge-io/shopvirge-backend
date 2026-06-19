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
# def test_categories_get_multi(test_client, category_1, category_2, superuser_token_headers):
#     response = test_client.get("/api/categories", headers=superuser_token_headers)
#     assert HTTPStatus.OK == response.status_code
#     categories = response.json()
#     assert 2 == len(categories)
#
#
# def test_category_get_by_id(category_2, test_client, superuser_token_headers):
#     response = test_client.get(f"/api/categories/{category_2.id}", headers=superuser_token_headers)
#     assert HTTPStatus.OK == response.status_code
#     category = response.json()
#     assert category["name"] == "Category 2"
#
#
# def test_category_get_by_id_404(category_1, test_client, superuser_token_headers):
#     response = test_client.get(f"/api/categories/{str(uuid4())}", headers=superuser_token_headers)
#     assert HTTPStatus.NOT_FOUND == response.status_code
#
#
# def test_category_save(test_client, superuser_token_headers, shop_1, category_1, category_2, main_category_1):
#     body = {
#         "name": "New category",
#         "description": "Category Description",
#         "icon": "New Icon",
#         "color": "#ffffff",
#         "shop_id": shop_1.id,
#         "main_category_id": main_category_1.id,
#     }
#     response = test_client.post("/api/categories/", content=json_dumps(body), headers=superuser_token_headers)
#     assert HTTPStatus.CREATED == response.status_code
#     categories = test_client.get("/api/categories", headers=superuser_token_headers).json()
#     assert 3 == len(categories)
#
#
# def test_category_update(category_1, test_client, superuser_token_headers, shop_1, main_category_1):
#     body = {
#         "name": "Updated category",
#         "description": "Updated Category Description",
#         "icon": "Updated Icon",
#         "color": "#ffffff",
#         "shop_id": shop_1.id,
#         "main_category_id": main_category_1.id,
#     }
#     response = test_client.put(
#         f"/api/categories/{category_1.id}", content=json_dumps(body), headers=superuser_token_headers
#     )
#     assert HTTPStatus.CREATED == response.status_code
#
#     response_updated = test_client.get(f"/api/categories/{category_1.id}", headers=superuser_token_headers)
#     category = response_updated.json()
#     assert category["name"] == "Updated category"
#
#
# def test_category_delete(category_1, category_2, test_client, superuser_token_headers):
#     response = test_client.delete(f"/api/categories/{category_1.id}", headers=superuser_token_headers)
#     assert HTTPStatus.NO_CONTENT == response.status_code
#     categories = test_client.get("/api/categories", headers=superuser_token_headers).json()
#     assert 1 == len(categories)
