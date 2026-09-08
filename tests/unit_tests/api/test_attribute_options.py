from http import HTTPStatus

from server.db import db
from server.db.models import AttributeOptionTable


def test_list_attribute_options(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    resp = test_client.get(f"/shops/{shop_id}/attributes/{attr_id}/options/")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert len(data) >= 1
    assert any(opt["id"] == str(ids["opt1a_id"]) for opt in data)
    # Verify that the response contains the expected attribute option


def test_get_attribute_option(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]
    option_id = ids["opt1a_id"]

    resp = test_client.get(f"/shops/{shop_id}/attributes/{attr_id}/options/{option_id}")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data["id"] == str(option_id)
    assert data["attribute_id"] == str(attr_id)


def test_create_attribute_option(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    new_option = {"value_key": "NewOption"}
    resp = test_client.post(f"/shops/{shop_id}/attributes/{attr_id}/options/", json=new_option)
    assert resp.status_code == HTTPStatus.CREATED
    data = resp.json()
    assert data["value_key"] == "NewOption"
    assert data["attribute_id"] == str(attr_id)

    # Verify in DB
    option = db.session.query(AttributeOptionTable).filter_by(id=data["id"]).first()
    assert option is not None
    assert option.value_key == "NewOption"


def test_create_attribute_option_duplicate(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]
    # Get an existing value_key
    existing_option = db.session.query(AttributeOptionTable).filter_by(attribute_id=attr_id).first()

    new_option = {"value_key": existing_option.value_key}
    resp = test_client.post(f"/shops/{shop_id}/attributes/{attr_id}/options/", json=new_option)
    assert resp.status_code == HTTPStatus.CONFLICT


def test_delete_attribute_option(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]
    option_id = ids["opt1a_id"]

    resp = test_client.delete(f"/shops/{shop_id}/attributes/{attr_id}/options/{option_id}")
    assert resp.status_code == HTTPStatus.NO_CONTENT

    # Verify in DB
    option = db.session.query(AttributeOptionTable).filter_by(id=option_id).first()
    assert option is None
