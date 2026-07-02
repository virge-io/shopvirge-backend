"""Tests for soft delete (trash), the query filter, restore and purge auth rules."""

import pytest
from fastapi.testclient import TestClient

from server.db import db
from server.db.models import ProductAttributeValueTable, ProductTable, ProductToTagTable, TagTable
from server.security import auth_required_any
from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.attribute import make_attribute, make_option, make_pav
from tests.unit_tests.factories.tag import make_tag


@pytest.fixture
def as_api_key(fastapi_app):
    """Temporarily authenticate ``auth_required_any`` routes as an API-key principal."""
    saved = fastapi_app.dependency_overrides[auth_required_any]

    def _activate(shop_id):
        row, _ = make_api_key(shop_id)
        fastapi_app.dependency_overrides[auth_required_any] = lambda: row
        return row

    yield _activate
    fastapi_app.dependency_overrides[auth_required_any] = saved


def test_deleted_product_hidden_everywhere(shop_with_config, product, test_client):
    resp = test_client.delete(f"/shops/{shop_with_config}/products/{product}")
    assert resp.status_code == 204

    # Row still exists, flagged deleted
    row = db.session.query(ProductTable).filter_by(id=product).execution_options(include_deleted=True).one()
    assert row.deleted_at is not None

    # Hidden from list and detail endpoints
    listing = test_client.get(f"/shops/{shop_with_config}/products/").json()
    assert str(product) not in [p["id"] for p in listing]
    assert test_client.get(f"/shops/{shop_with_config}/products/{product}").status_code == 404

    # Deleting it again is a 404 (it's no longer visible)
    assert test_client.delete(f"/shops/{shop_with_config}/products/{product}").status_code == 404


def test_trash_and_restore_product_with_relations(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="keepme")
    db.session.add(ProductToTagTable(shop_id=shop_with_config, product_id=product, tag_id=tag_id))
    db.session.commit()
    attr_id = make_attribute(shop_with_config, name="size")
    opt_id = make_option(attr_id, "M")
    make_pav(product, attr_id, opt_id)

    assert test_client.delete(f"/shops/{shop_with_config}/products/{product}").status_code == 204

    trash = test_client.get(f"/shops/{shop_with_config}/trash").json()
    trashed_ids = [t["id"] for t in trash if t["entity_type"] == "product"]
    assert str(product) in trashed_ids

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/restore")
    assert resp.status_code == 200, resp.json()
    assert resp.json()["restored"] is True

    # Product is visible again with tags and attribute values intact
    assert test_client.get(f"/shops/{shop_with_config}/products/{product}").status_code == 200
    assert db.session.query(ProductToTagTable).filter_by(product_id=product, tag_id=tag_id).count() == 1
    assert db.session.query(ProductAttributeValueTable).filter_by(product_id=product).count() == 1
    assert test_client.get(f"/shops/{shop_with_config}/trash").json() == []


def test_purge_requires_cognito(shop_with_config, product, test_client, fastapi_app, as_api_key):
    as_api_key(shop_with_config)
    api_client = TestClient(fastapi_app)

    # API key may trash…
    resp = api_client.delete(f"/shops/{shop_with_config}/products/{product}?force=true")
    assert resp.status_code == 403

    # …but not purge
    resp = api_client.delete(f"/shops/{shop_with_config}/products/{product}")
    assert resp.status_code == 204


def test_purge_with_cognito_removes_row(shop_with_config, product, test_client):
    assert test_client.delete(f"/shops/{shop_with_config}/products/{product}").status_code == 204
    # Purge from the trash with user credentials
    assert test_client.delete(f"/shops/{shop_with_config}/products/{product}?force=true").status_code == 204
    row = db.session.query(ProductTable).filter_by(id=product).execution_options(include_deleted=True).first()
    assert row is None


def test_api_key_actor_recorded_in_revision(shop_with_config, product, test_client, fastapi_app, as_api_key):
    from server.db.models import RevisionTable

    key_row = as_api_key(shop_with_config)
    api_client = TestClient(fastapi_app)
    assert api_client.delete(f"/shops/{shop_with_config}/products/{product}").status_code == 204

    revision = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product)
        .order_by(RevisionTable.revision_no.desc())
        .first()
    )
    assert revision.action == "delete"
    assert revision.created_by == f"api_key:{key_row.id}"


def test_soft_deleted_tag_filtered_from_relationship_loads(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="hidden-tag")
    db.session.add(ProductToTagTable(shop_id=shop_with_config, product_id=product, tag_id=tag_id))
    db.session.commit()

    assert test_client.delete(f"/shops/{shop_with_config}/tags/{tag_id}").status_code == 204
    db.session.expire_all()

    # Top-level query filtered
    assert db.session.query(TagTable).filter_by(id=tag_id).first() is None
    # Relationship load from a queried parent is filtered too
    row = db.session.query(ProductTable).filter_by(id=product).one()
    assert tag_id not in [t.id for t in row.tags]
    # Opt-out sees it
    assert db.session.query(TagTable).filter_by(id=tag_id).execution_options(include_deleted=True).first() is not None

    # Restoring the tag brings the product link back without any relinking
    tag_row = db.session.query(TagTable).filter_by(id=tag_id).execution_options(include_deleted=True).one()
    tag_row.deleted_at = None
    db.session.commit()
    db.session.expire_all()
    row = db.session.query(ProductTable).filter_by(id=product).one()
    assert tag_id in [t.id for t in row.tags]
