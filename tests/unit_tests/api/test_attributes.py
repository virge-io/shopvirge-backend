from http import HTTPStatus

from server.db import db
from server.db.models import AttributeTable


def test_get_attributes_with_options(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]

    resp = test_client.get(f"/shops/{shop_id}/attributes/with-options")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert len(data) >= 2
    attr_ids = {attr["id"] for attr in data}
    assert str(ids["attr1_id"]) in attr_ids
    assert str(ids["attr2_id"]) in attr_ids

    # Check if options are present
    attr1 = next(a for a in data if a["id"] == str(ids["attr1_id"]))
    assert any(opt["id"] == str(ids["opt1a_id"]) for opt in attr1["options"])
    # Verify that the response contains the expected attributes with options


def test_get_attribute_by_id(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    resp = test_client.get(f"/shops/{shop_id}/attributes/id/{attr_id}")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data["id"] == str(attr_id)


def test_create_attribute(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]

    new_attr = {"name": "Material", "unit": "string"}
    resp = test_client.post(f"/shops/{shop_id}/attributes/", json=new_attr)
    assert resp.status_code == HTTPStatus.CREATED

    # Verify in DB
    attr = db.session.query(AttributeTable).filter_by(shop_id=shop_id, name="Material").first()
    assert attr is not None
    assert attr.unit == "string"


def test_create_attribute_duplicate(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_name = "Color"

    # This could probably be improved'

    # First ensure it exists
    existing = db.session.query(AttributeTable).filter_by(shop_id=shop_id, name=attr_name).first()
    if not existing:
        # If "Color" doesn't exist, use one that does
        existing = db.session.query(AttributeTable).filter_by(shop_id=shop_id).first()
        attr_name = existing.name

    new_attr = {"name": attr_name, "unit": "string"}
    resp = test_client.post(f"/shops/{shop_id}/attributes/", json=new_attr)
    assert resp.status_code == HTTPStatus.CONFLICT


def test_update_attribute(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    update_data = {
        "name": "Updated Name",
        "unit": "cm",
        "shop_id": str(shop_id),
        "translation": {"main_name": "Updated Name"},
    }
    resp = test_client.put(f"/shops/{shop_id}/attributes/{attr_id}", json=update_data)
    assert resp.status_code == HTTPStatus.OK

    # Verify
    attr = db.session.query(AttributeTable).filter_by(id=attr_id).first()
    assert attr.name == "Updated Name"
    assert attr.unit == "cm"


def test_get_attribute_by_id_with_options(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    # This endpoint doesn't exist yet
    resp = test_client.get(f"/shops/{shop_id}/attributes/id/{attr_id}/with-options")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data["id"] == str(attr_id)
    assert any(opt["id"] == str(ids["opt1a_id"]) for opt in data["options"])
    # Verify that the response contains the expected attribute with options


def test_get_attribute_by_id_with_options_direct(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    resp = test_client.get(f"/shops/{shop_id}/attributes/{attr_id}/with-options")
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data["id"] == str(attr_id)
    assert any(opt["id"] == str(ids["opt1a_id"]) for opt in data["options"])
    # Verify that the response contains the expected attribute with options


def test_create_attribute_fixed(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]

    new_attr = {"name": "Test Attribute", "unit": "kg"}
    resp = test_client.post(f"/shops/{shop_id}/attributes/", json=new_attr)
    assert resp.status_code == HTTPStatus.CREATED
    data = resp.json()
    assert data["name"] == "Test Attribute"
    assert data["unit"] == "kg"

    # Verify in DB
    attr = db.session.query(AttributeTable).filter_by(shop_id=shop_id, name="Test Attribute").first()
    assert attr is not None
    assert attr.unit == "kg"


def test_update_attribute_empty_body(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    # Original data
    attr_before = db.session.query(AttributeTable).get(attr_id)
    name_before = attr_before.name
    unit_before = attr_before.unit

    # Empty body update
    resp = test_client.put(f"/shops/{shop_id}/attributes/{attr_id}", json={})
    assert resp.status_code == HTTPStatus.OK

    # Should remain unchanged
    attr_after = db.session.query(AttributeTable).get(attr_id)
    assert attr_after.name == name_before
    assert attr_after.unit == unit_before


def test_update_attribute_valid_data(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    update_data = {"name": "New Name", "unit": "new unit"}
    resp = test_client.put(f"/shops/{shop_id}/attributes/{attr_id}", json=update_data)
    assert resp.status_code == HTTPStatus.OK
    data = resp.json()
    assert data["name"] == "New Name"
    assert data["unit"] == "new unit"

    # Verify in DB
    attr = db.session.query(AttributeTable).get(attr_id)
    assert attr.name == "New Name"
    assert attr.unit == "new unit"
