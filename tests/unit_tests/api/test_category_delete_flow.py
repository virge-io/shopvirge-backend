"""Tests for the category delete flow: 409 warning, force cascade, detach, batch restore
and category revision restore."""

from server.db import db
from server.db.models import CategoryTable, ProductTable, RevisionTable
from server.utils.json import json_dumps
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product


def category_body(shop_id, main_name, color="#FFFFFF"):
    return {
        "shop_id": str(shop_id),
        "color": color,
        "translation": {"main_name": main_name, "main_description": f"{main_name} description"},
        "main_image": "",
        "alt1_image": "",
        "alt2_image": "",
    }


def get_product(product_id, include_deleted=True):
    # Endpoint writes happen in a different (request) session on the same connection;
    # expire cached instances so we read the current DB state, not the identity map.
    db.session.expire_all()
    return (
        db.session.query(ProductTable).filter_by(id=product_id).execution_options(include_deleted=include_deleted).one()
    )


def test_delete_category_with_products_warns_409(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config)
    make_product(shop_id=shop_with_config, category_id=category)
    make_product(shop_id=shop_with_config, category_id=category, main_name="Second product")

    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["product_count"] == 2
    assert "force=true" in detail["hint"]
    assert "detach=true" in detail["hint"]

    # Nothing was deleted
    assert db.session.query(CategoryTable).filter_by(id=category).first() is not None


def test_force_and_detach_are_mutually_exclusive(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config)
    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}?force=true&detach=true")
    assert resp.status_code == 422


def test_empty_category_delete_is_soft(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config)
    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}")
    assert resp.status_code == 204

    assert db.session.query(CategoryTable).filter_by(id=category).first() is None
    row = db.session.query(CategoryTable).filter_by(id=category).execution_options(include_deleted=True).one()
    assert row.deleted_at is not None


def test_force_cascade_and_batch_restore(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config)
    product_1 = make_product(shop_id=shop_with_config, category_id=category)
    product_2 = make_product(shop_id=shop_with_config, category_id=category, main_name="Second product")
    trashed_before = make_product(shop_id=shop_with_config, category_id=category, main_name="Trashed earlier")
    assert test_client.delete(f"/shops/{shop_with_config}/products/{trashed_before}").status_code == 204

    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}?force=true")
    assert resp.status_code == 204

    # Both live products were trashed under one batch id; each got a delete revision
    row_1, row_2 = get_product(product_1), get_product(product_2)
    assert row_1.deleted_at is not None and row_2.deleted_at is not None
    assert row_1.deleted_batch_id == row_2.deleted_batch_id is not None
    for product_id in (product_1, product_2):
        last = (
            db.session.query(RevisionTable)
            .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product_id)
            .order_by(RevisionTable.revision_no.desc())
            .first()
        )
        assert last.action == "delete"
    # The previously trashed product is NOT part of the batch
    assert get_product(trashed_before).deleted_batch_id is None

    # Restore the category with its batch
    resp = test_client.post(f"/shops/{shop_with_config}/categories/{category}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    restored_kinds = [r["kind"] for r in report["resurrected"]]
    assert restored_kinds.count("product") == 2

    assert db.session.query(CategoryTable).filter_by(id=category).first() is not None
    assert get_product(product_1).deleted_at is None
    assert get_product(product_2).deleted_at is None
    # The product trashed before the cascade stays in the trash
    assert get_product(trashed_before).deleted_at is not None


def test_detach_keeps_products_without_category(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config, main_name="Doomed category")
    product_id = make_product(shop_id=shop_with_config, category_id=category)

    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}?detach=true")
    assert resp.status_code == 204

    # Category trashed, product alive without a category
    assert db.session.query(CategoryTable).filter_by(id=category).first() is None
    row = get_product(product_id, include_deleted=False)
    assert row.deleted_at is None
    assert row.category_id is None

    # Product endpoints must keep serializing detached products (category_id is None)
    resp = test_client.get(f"/shops/{shop_with_config}/products/")
    assert resp.status_code == 200, resp.text
    listed = {item["id"]: item for item in resp.json()}
    assert listed[str(product_id)]["category_id"] is None
    resp = test_client.get(f"/shops/{shop_with_config}/products/{product_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["category_id"] is None

    # The detach was recorded on the product with a pointer to the old category
    last = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product_id)
        .order_by(RevisionTable.revision_no.desc())
        .first()
    )
    assert last.action == "update"
    assert last.data["detached_from_category"]["id"] == str(category)
    assert last.data["detached_from_category"]["name"] == "Doomed category"
    assert last.data["category"] is None


def test_restore_category_revision_undoes_rename(shop_with_config, test_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/categories/", content=json_dumps(category_body(shop_with_config, "Good name"))
    )
    assert resp.status_code == 201, resp.text
    category_id = resp.json()["id"]

    body = category_body(shop_with_config, "LLM made a mess", color="#000000")
    resp = test_client.put(f"/shops/{shop_with_config}/categories/{category_id}", content=json_dumps(body))
    assert resp.status_code == 201, resp.text

    resp = test_client.post(f"/shops/{shop_with_config}/categories/{category_id}/revisions/1/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["entity_type"] == "category"

    db.session.expire_all()
    row = db.session.query(CategoryTable).filter_by(id=category_id).one()
    assert row.translation.main_name == "Good name"
    assert row.color == "#FFFFFF"
    last = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "category", RevisionTable.entity_id == category_id)
        .order_by(RevisionTable.revision_no.desc())
        .first()
    )
    assert last.action == "restore"


def test_restore_purged_category_revision_requires_force(shop_with_config, test_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/categories/", content=json_dumps(category_body(shop_with_config, "Purged"))
    )
    category_id = resp.json()["id"]

    # Hard-purge the row directly (the API only ever trashes categories)
    row = db.session.query(CategoryTable).filter_by(id=category_id).one()
    if row.translation:
        db.session.delete(row.translation)
    db.session.delete(row)
    db.session.commit()

    assert (
        test_client.post(f"/shops/{shop_with_config}/categories/{category_id}/revisions/1/restore").status_code == 410
    )

    resp = test_client.post(f"/shops/{shop_with_config}/categories/{category_id}/revisions/1/restore?force=true")
    assert resp.status_code == 200, resp.json()
    assert any("recreated" in w for w in resp.json()["warnings"])
    db.session.expire_all()
    row = db.session.query(CategoryTable).filter_by(id=category_id).one()
    assert row.translation.main_name == "Purged"


def test_restore_category_without_products_flag(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config)
    product_id = make_product(shop_id=shop_with_config, category_id=category)
    assert test_client.delete(f"/shops/{shop_with_config}/categories/{category}?force=true").status_code == 204

    resp = test_client.post(f"/shops/{shop_with_config}/categories/{category}/restore?restore_products=false")
    assert resp.status_code == 200
    assert db.session.query(CategoryTable).filter_by(id=category).first() is not None
    assert get_product(product_id).deleted_at is not None
