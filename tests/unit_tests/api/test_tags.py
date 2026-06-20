from server.db.models import TagTable
from server.utils.json import json_dumps


def test_tags_get_multi(shop_with_tags, test_client):
    response = test_client.get(f"/shops/{shop_with_tags}/tags/")
    assert response.status_code == 200
    tags = response.json()
    assert 2 == len(tags)


def test_tags_get_by_id(shop, tag, test_client):
    response = test_client.get(f"/shops/{shop}/tags/{tag}")
    assert response.status_code == 200
    tag = response.json()
    assert tag["translation"]["main_name"] == "Tag for Testing"


def test_tags_create(shop, test_client):
    body = {
        "shop_id": shop,
        "name": "Create Tag Test",
        "translation": {
            "main_name": "Create Tag Test",
            "alt1_name": "Update Tag Test Alt1",
            "alt2_name": "Update Tag Test Alt2",
        },
    }

    response = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(body))
    assert response.status_code == 201
    tag = TagTable.query.filter_by(id=response.json()["id"]).first()
    assert tag.translation.main_name == "Create Tag Test"


def test_tags_update(shop, tag, test_client):
    body = {
        "shop_id": shop,
        "name": "Update Tag Test",
        "translation": {
            "main_name": "Update Tag Test",
            "alt1_name": "Update Tag Test Alt1",
            "alt2_name": "Update Tag Test Alt2",
        },
    }

    response = test_client.put(f"/shops/{shop}/tags/{tag}", content=json_dumps(body))
    assert response.status_code == 201
    tag = TagTable.query.filter_by(id=tag).first()
    assert tag.translation.main_name == "Update Tag Test"


def test_tags_delete(shop, tag, test_client):
    response = test_client.delete(f"/shops/{shop}/tags/{tag}")
    assert response.status_code == 204
