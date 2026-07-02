"""Tests for baseline revisions.

Entities created before revision tracking shipped have no revision rows. Without a
baseline, their first edit would record the *post*-edit state as revision 1 and the
old data would be lost. The first mutation therefore captures the pre-mutation state
as a ``baseline`` revision, making that first edit undoable.
"""

from server.db import db
from server.db.models import ProductTable, RevisionTable
from server.utils.json import json_dumps
from tests.unit_tests.api.test_product_revisions import product_body, product_category_id, revision_rows
from tests.unit_tests.factories.categories import make_category
from tests.unit_tests.factories.product import make_product
from tests.unit_tests.factories.tag import make_tag


def test_first_edit_captures_baseline_and_is_undoable(shop_with_config, product, test_client):
    category = product_category_id(product)
    body = test_client.put(
        f"/shops/{shop_with_config}/products/{product}",
        content=json_dumps(product_body(shop_with_config, category, main_name="LLM made a mess", price=999.0)),
    )
    assert body.status_code == 201, body.json()

    rows = revision_rows(product)
    assert [r.action for r in rows] == ["baseline", "update"]
    baseline = rows[0]
    # The baseline holds the pre-edit data, unattributed: it was authored before tracking existed
    assert baseline.data["translation"]["main_name"] == "Product for Testing"
    assert float(baseline.data["product"]["price"]) == 1.0
    assert baseline.created_by is None

    # Undo the very first edit by restoring the baseline
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/1/restore")
    assert resp.status_code == 200, resp.json()
    product_resp = test_client.get(f"/shops/{shop_with_config}/products/{product}").json()
    assert product_resp["translation"]["main_name"] == "Product for Testing"
    assert float(product_resp["price"]) == 1.0


def test_baseline_is_recorded_only_once(shop_with_config, product, test_client):
    category = product_category_id(product)
    for i in range(3):
        resp = test_client.put(
            f"/shops/{shop_with_config}/products/{product}",
            content=json_dumps(product_body(shop_with_config, category, main_name=f"Edit {i}")),
        )
        assert resp.status_code == 201, resp.json()

    rows = revision_rows(product)
    assert [r.action for r in rows] == ["baseline", "update", "update", "update"]


def test_products_created_via_api_get_no_baseline(shop, category, test_client):
    resp = test_client.post(
        f"/shops/{shop}/products/", content=json_dumps(product_body(shop, category, main_name="Fresh product"))
    )
    assert resp.status_code == 201, resp.json()
    product_id = resp.json()["id"]

    resp = test_client.put(
        f"/shops/{shop}/products/{product_id}",
        content=json_dumps(product_body(shop, category, main_name="Fresh product v2")),
    )
    assert resp.status_code == 201, resp.json()

    rows = revision_rows(product_id)
    assert [r.action for r in rows] == ["create", "update"]


def test_tag_link_baseline_excludes_pending_link(shop_with_config, product, test_client):
    """The baseline reflects the state before the mutation that triggered it."""
    tag_id = make_tag(shop_id=shop_with_config, main_name="first-tag")
    resp = test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    assert resp.status_code == 204, resp.text

    rows = revision_rows(product)
    assert [r.action for r in rows] == ["baseline", "update"]
    assert rows[0].data["tags"] == []
    assert rows[1].data["tags"] == [{"id": str(tag_id), "name": "first-tag"}]


def test_trash_needs_no_baseline(shop_with_config, product, test_client):
    """A delete revision already snapshots the pre-delete state; no baseline is added."""
    assert test_client.delete(f"/shops/{shop_with_config}/products/{product}").status_code == 204

    rows = revision_rows(product)
    assert [r.action for r in rows] == ["delete"]
    assert rows[0].data["translation"]["main_name"] == "Product for Testing"


def test_category_first_edit_captures_baseline(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config, main_name="Legacy category")
    body = {
        "shop_id": str(shop_with_config),
        "color": "#FFFFFF",
        "translation": {"main_name": "Renamed category", "main_description": "Updated"},
        "main_image": "",
        "alt1_image": "",
        "alt2_image": "",
    }
    resp = test_client.put(f"/shops/{shop_with_config}/categories/{category}", content=json_dumps(body))
    assert resp.status_code == 201, resp.json()

    rows = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "category", RevisionTable.entity_id == category)
        .order_by(RevisionTable.revision_no)
        .all()
    )
    assert [r.action for r in rows] == ["baseline", "update"]
    assert rows[0].data["translation"]["main_name"] == "Legacy category"
    assert rows[1].data["translation"]["main_name"] == "Renamed category"


def test_detach_captures_product_baseline_with_old_category(shop_with_config, test_client):
    category = make_category(shop_id=shop_with_config, main_name="Detach source")
    product_id = make_product(shop_id=shop_with_config, category_id=category)

    resp = test_client.delete(f"/shops/{shop_with_config}/categories/{category}?detach=true")
    assert resp.status_code == 204

    rows = revision_rows(product_id)
    assert [r.action for r in rows] == ["baseline", "update"]
    # Baseline preserves the product's pre-detach category; the update shows it cleared
    assert rows[0].data["category"]["id"] == str(category)
    assert rows[1].data["category"] is None
