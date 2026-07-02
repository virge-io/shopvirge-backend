"""Tests for product revision snapshots and restores."""

from http import HTTPStatus
from uuid import UUID, uuid4

import pytest

from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeTable,
    CategoryTable,
    ProductAttributeValueTable,
    ProductTable,
    ProductToTagTable,
    RevisionTable,
    TagTable,
)
from server.utils.json import json_dumps
from tests.unit_tests.factories.attribute import make_attribute, make_option
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.tag import make_tag


def product_body(shop_id, category_id, main_name="Revision Test Product", price=1.0):
    return {
        "shop_id": str(shop_id),
        "category_id": str(category_id),
        "price": price,
        "tax_category": "vat_zero",
        "max_one": False,
        "shippable": True,
        "featured": False,
        "new_product": False,
        "translation": {
            "main_name": main_name,
            "main_description": "Description",
            "main_description_short": "Short description",
        },
        "image_1": "",
        "image_2": "",
        "image_3": "",
        "image_4": "",
        "image_5": "",
        "image_6": "",
    }


def product_category_id(product_id):
    return db.session.query(ProductTable).filter_by(id=product_id).one().category_id


def revision_rows(product_id):
    return (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product_id)
        .order_by(RevisionTable.revision_no)
        .all()
    )


def test_create_records_revision(shop, category, test_client):
    response = test_client.post(f"/shops/{shop}/products/", content=json_dumps(product_body(shop, category)))
    assert response.status_code == HTTPStatus.CREATED, response.json()
    product_id = UUID(response.json()["id"])

    rows = revision_rows(product_id)
    assert len(rows) == 1
    assert rows[0].revision_no == 1
    assert rows[0].action == "create"
    assert rows[0].created_by == "cognito:5678"
    assert rows[0].source == "rest"
    assert rows[0].data["translation"]["main_name"] == "Revision Test Product"


def test_updates_append_revisions_and_are_listable(shop_with_config, product, test_client):
    category = product_category_id(product)
    for i, price in enumerate([2.0, 3.0]):
        body = product_body(shop_with_config, category, main_name=f"Name v{i}", price=price)
        resp = test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body))
        assert resp.status_code == 201, resp.json()

    resp = test_client.get(f"/shops/{shop_with_config}/products/{product}/revisions")
    assert resp.status_code == 200
    revisions = resp.json()
    assert len(revisions) == 2
    # Newest first
    assert revisions[0]["revision_no"] == 2
    assert revisions[0]["action"] == "update"
    assert revisions[0]["name"] == "Name v1"
    assert revisions[1]["name"] == "Name v0"

    detail = test_client.get(f"/shops/{shop_with_config}/products/{product}/revisions/1").json()
    assert detail["data"]["product"]["price"] == 2.0
    assert detail["data"]["translation"]["main_name"] == "Name v0"
    assert detail["data"]["category"] is not None


def test_tag_and_attribute_mutations_record_revisions(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="revtag")
    resp = test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    assert resp.status_code == 204, resp.text

    attr_id = make_attribute(shop_with_config, name="size")
    opt_id = make_option(attr_id, "XL")
    resp = test_client.put(
        f"/shops/{shop_with_config}/product-attribute-values/{product}",
        json={"option_ids": [str(opt_id)]},
    )
    assert resp.status_code == 204, resp.text

    rows = revision_rows(product)
    assert [r.action for r in rows] == ["update", "update"]
    latest = rows[-1].data
    assert latest["tags"] == [{"id": str(tag_id), "name": "revtag"}]
    assert latest["attribute_values"] == [
        {
            "attribute_id": str(attr_id),
            "attribute_name": "size",
            "option_id": str(opt_id),
            "option_value_key": "XL",
        }
    ]


def test_restore_previous_revision(shop_with_config, product, test_client):
    category = product_category_id(product)
    body_v1 = product_body(shop_with_config, category, main_name="Original name", price=10.0)
    body_v2 = product_body(shop_with_config, category, main_name="LLM made a mess", price=999.0)
    assert (
        test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body_v1)).status_code == 201
    )
    assert (
        test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body_v2)).status_code == 201
    )

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/1/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["restored_from_revision_no"] == 1
    assert report["new_revision_no"] == 3
    assert report["unresolved"] == []
    assert report["skipped_fields"] == []

    product_resp = test_client.get(f"/shops/{shop_with_config}/products/{product}").json()
    assert product_resp["translation"]["main_name"] == "Original name"
    assert float(product_resp["price"]) == 10.0

    rows = revision_rows(product)
    assert rows[-1].action == "restore"


def test_restore_resurrects_soft_deleted_references(shop_with_config, product, test_client):
    category = product_category_id(product)
    # Build the aggregate: tag + attribute value; the PAV PUT records the snapshot
    tag_id = make_tag(shop_id=shop_with_config, main_name="resurrect-me")
    test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    attr_id = make_attribute(shop_with_config, name="material")
    opt_id = make_option(attr_id, "WOOL")
    test_client.put(
        f"/shops/{shop_with_config}/product-attribute-values/{product}",
        json={"option_ids": [str(opt_id)]},
    )
    snapshot_revision_no = revision_rows(product)[-1].revision_no

    # Trash the tag and the attribute, then trash the category with the product (cascade)
    assert test_client.delete(f"/shops/{shop_with_config}/tags/{tag_id}").status_code == 204
    assert test_client.delete(f"/shops/{shop_with_config}/attributes/{attr_id}").status_code == 204
    assert test_client.delete(f"/shops/{shop_with_config}/categories/{category}?force=true").status_code == 204

    # Restore the snapshot revision — everything should come back
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{snapshot_revision_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["unresolved"] == []
    resurrected_kinds = {r["kind"] for r in report["resurrected"]}
    assert {"product", "category", "tag", "attribute"} <= resurrected_kinds

    assert db.session.query(ProductTable).filter_by(id=product).one().deleted_at is None
    assert db.session.query(CategoryTable).filter_by(id=category).one().deleted_at is None
    assert db.session.query(TagTable).filter_by(id=tag_id).one().deleted_at is None
    assert db.session.query(AttributeTable).filter_by(id=attr_id).one().deleted_at is None
    pavs = db.session.query(ProductAttributeValueTable).filter_by(product_id=product).all()
    assert [(p.attribute_id, p.option_id) for p in pavs] == [(attr_id, opt_id)]


def test_restore_matches_purged_tag_by_name(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="stable-name")
    test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    snapshot_revision_no = revision_rows(product)[-1].revision_no

    # Hard-purge the tag (links + row), then recreate it under a NEW id with the same name
    db.session.query(ProductToTagTable).filter_by(tag_id=tag_id).delete()
    tag_row = db.session.query(TagTable).filter_by(id=tag_id).one()
    if tag_row.translation:
        db.session.delete(tag_row.translation)
    db.session.delete(tag_row)
    db.session.commit()
    new_tag_id = make_tag(shop_id=shop_with_config, main_name="stable-name")

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{snapshot_revision_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["unresolved"] == []

    links = db.session.query(ProductToTagTable).filter_by(product_id=product).all()
    assert [link.tag_id for link in links] == [new_tag_id]


def test_restore_reports_unresolved_when_attribute_purged(shop_with_config, product, test_client):
    attr_id = make_attribute(shop_with_config, name="doomed")
    opt_id = make_option(attr_id, "GONE")
    test_client.put(
        f"/shops/{shop_with_config}/product-attribute-values/{product}",
        json={"option_ids": [str(opt_id)]},
    )
    snapshot_revision_no = revision_rows(product)[-1].revision_no

    # Hard-purge PAVs, option, translation and attribute
    db.session.query(ProductAttributeValueTable).filter_by(attribute_id=attr_id).delete()
    db.session.query(AttributeOptionTable).filter_by(attribute_id=attr_id).delete()
    attribute = db.session.query(AttributeTable).filter_by(id=attr_id).one()
    if attribute.translation:
        db.session.delete(attribute.translation)
    db.session.delete(attribute)
    db.session.commit()

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{snapshot_revision_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert any(u["kind"] == "attribute" and u["name"] == "doomed" for u in report["unresolved"])
    assert db.session.query(ProductAttributeValueTable).filter_by(product_id=product).count() == 0


def test_double_restore_is_idempotent(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="twice")
    test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    attr_id = make_attribute(shop_with_config, name="width")
    opt_id = make_option(attr_id, "S")
    test_client.put(
        f"/shops/{shop_with_config}/product-attribute-values/{product}",
        json={"option_ids": [str(opt_id)]},
    )
    snapshot_revision_no = revision_rows(product)[-1].revision_no

    for _ in range(2):
        resp = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/revisions/{snapshot_revision_no}/restore"
        )
        assert resp.status_code == 200, resp.json()

    # No duplicated links or attribute values
    assert db.session.query(ProductToTagTable).filter_by(product_id=product).count() == 1
    assert db.session.query(ProductAttributeValueTable).filter_by(product_id=product).count() == 1


def test_model_churn_round_trip(shop_with_config, product, test_client):
    category = product_category_id(product)
    """Snapshot → restore must reproduce every mapped column (guards future model churn)."""
    from sqlalchemy.inspection import inspect as sa_inspect

    body = product_body(shop_with_config, category, main_name="Churn guard", price=42.5)
    assert test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body)).status_code == 201

    row = db.session.query(ProductTable).filter_by(id=product).one()
    ignored = {"deleted_at", "deleted_batch_id", "created_at", "modified_at"}
    before = {key: getattr(row, key) for key in sa_inspect(ProductTable).columns.keys() if key not in ignored}

    latest_no = revision_rows(product)[-1].revision_no
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{latest_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["skipped_fields"] == [], "snapshot contains fields restore can no longer apply"
    assert report["unresolved"] == []

    row = db.session.query(ProductTable).filter_by(id=product).one()
    after = {key: getattr(row, key) for key in before}
    assert before == after


def test_unknown_snapshot_keys_are_skipped_not_fatal(shop_with_config, product, test_client):
    category = product_category_id(product)
    body = product_body(shop_with_config, category)
    assert test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body)).status_code == 201

    # Simulate a snapshot written by a future model version with an extra column
    revision = revision_rows(product)[-1]
    data = dict(revision.data)
    data["product"] = {**data["product"], "column_from_the_future": "value"}
    revision.data = data
    db.session.commit()

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{revision.revision_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert "product.column_from_the_future" in report["skipped_fields"]


def test_restore_missing_revision_404(shop_with_config, product, test_client):
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/99/restore")
    assert resp.status_code == 404


def test_restore_unknown_schema_version_422(shop_with_config, product, test_client):
    category = product_category_id(product)
    body = product_body(shop_with_config, category)
    assert test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body)).status_code == 201
    revision = revision_rows(product)[-1]
    revision.schema_version = 0  # no up-converter registered for 0
    db.session.commit()

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{revision.revision_no}/restore")
    assert resp.status_code == 422
