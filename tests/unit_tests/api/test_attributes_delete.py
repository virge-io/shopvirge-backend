from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable, AttributeTranslationTable, ProductAttributeValueTable
from tests.unit_tests.factories.attribute import make_attribute, make_option, make_pav


def test_delete_attribute_soft_deletes_by_default(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]
    opt_a_id = ids["opt1a_id"]
    product_id = ids["product_id"]

    # Seed some PAVs — soft delete is allowed even while the attribute is in use
    make_pav(product_id, attr_id, opt_a_id)

    resp = test_client.delete(f"/shops/{shop_id}/attributes/{attr_id}")
    assert resp.status_code == 204

    # Hidden from normal queries...
    assert db.session.query(AttributeTable).filter_by(id=attr_id).first() is None
    # ...but the row, its options and the PAV data are all still there
    row = db.session.query(AttributeTable).filter_by(id=attr_id).execution_options(include_deleted=True).first()
    assert row is not None and row.deleted_at is not None
    assert db.session.query(ProductAttributeValueTable).filter_by(attribute_id=attr_id).count() == 1


def test_purge_attribute_blocked_by_products(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]
    opt_a_id = ids["opt1a_id"]
    product_id = ids["product_id"]

    # Seed some PAVs
    make_pav(product_id, attr_id, opt_a_id)

    # Hard purge should fail with 409 while in use
    resp = test_client.delete(f"/shops/{shop_id}/attributes/{attr_id}?force=true")
    assert resp.status_code == 409
    data = resp.json()
    assert data["detail"]["message"] == "Attribute is in use and cannot be deleted"


def test_purge_attribute_success_no_products(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    shop_id = ids["shop_id"]
    attr_id = ids["attr1_id"]

    # Pre-verification
    assert db.session.query(AttributeTable).filter_by(id=attr_id).first() is not None

    # Perform hard purge
    resp = test_client.delete(f"/shops/{shop_id}/attributes/{attr_id}?force=true")
    assert resp.status_code == 204

    # Post-verification: Attribute should be gone (even when including trashed rows)
    assert (
        db.session.query(AttributeTable).filter_by(id=attr_id).execution_options(include_deleted=True).first() is None
    )
    # Options and translations should also be gone due to SQLAlchemy cascade
    assert (
        db.session.query(AttributeOptionTable)
        .filter_by(attribute_id=attr_id)
        .execution_options(include_deleted=True)
        .count()
        == 0
    )
    assert db.session.query(AttributeTranslationTable).filter_by(attribute_id=attr_id).count() == 0


def test_delete_attribute_scoping(test_client, shop_with_products_and_attributes):
    ids = shop_with_products_and_attributes
    attr_id = ids["attr1_id"]
    other_shop_id = ids["other_shop_id"]

    # Try to delete attribute from wrong shop
    resp = test_client.delete(f"/shops/{other_shop_id}/attributes/{attr_id}")
    assert resp.status_code == 404

    # Ensure it's still there
    assert db.session.query(AttributeTable).filter_by(id=attr_id).first() is not None
