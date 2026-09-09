"""A restore whose snapshot matches the current state must not record a new
revision — it returns a warning instead, so the history doesn't fill up with no-ops.
"""

from uuid import UUID

from server.utils.json import json_dumps
from tests.unit_tests.api.test_category_delete_flow import category_body
from tests.unit_tests.api.test_product_revisions import product_body, product_category_id, revision_rows
from tests.unit_tests.api.test_shop_revision_feed import entity_revisions, tag_body


def assert_noop(resp, entity_type, entity_id, revision_count_before):
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["new_revision_no"] is None
    assert any("no-op" in warning for warning in report["warnings"])
    assert len(entity_revisions(entity_type, entity_id)) == revision_count_before


def test_product_noop_restore_records_no_revision(shop_with_config, product, test_client):
    category = product_category_id(product)
    body = product_body(shop_with_config, category, main_name="Current state", price=7.5)
    assert test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body)).status_code == 201

    rows = revision_rows(product)  # baseline + update
    latest_no = rows[-1].revision_no
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{latest_no}/restore")
    assert_noop(resp, "product", product, len(rows))

    # A revision that differs still records a restore revision
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/1/restore")
    assert resp.status_code == 200
    assert resp.json()["new_revision_no"] is not None


def test_tag_noop_restore_records_no_revision(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(tag_body(shop, "stable")))
    tag_id = UUID(resp.json()["id"])

    resp = test_client.post(f"/shops/{shop}/tags/{tag_id}/revisions/1/restore")
    assert_noop(resp, "tag", tag_id, 1)


def test_attribute_noop_restore_records_no_revision(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/attributes/", json={"name": "steady"})
    attr_id = UUID(resp.json()["id"])
    assert (
        test_client.post(
            f"/shops/{shop}/attribute-options/", json={"attribute_id": str(attr_id), "value_key": "ON"}
        ).status_code
        == 201
    )

    latest_no = entity_revisions("attribute", attr_id)[-1].revision_no
    resp = test_client.post(f"/shops/{shop}/attributes/{attr_id}/revisions/{latest_no}/restore")
    assert_noop(resp, "attribute", attr_id, 2)


def test_category_noop_restore_records_no_revision(shop_with_config, test_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/categories/", content=json_dumps(category_body(shop_with_config, "Steady"))
    )
    category_id = UUID(resp.json()["id"])

    resp = test_client.post(f"/shops/{shop_with_config}/categories/{category_id}/revisions/1/restore")
    assert_noop(resp, "category", category_id, 1)


def test_trashed_entity_restore_is_never_a_noop(shop_with_config, test_client):
    """Resurrection counts as a change even when the content matches the snapshot."""
    resp = test_client.post(
        f"/shops/{shop_with_config}/tags/", content=json_dumps(tag_body(shop_with_config, "trash-me"))
    )
    tag_id = UUID(resp.json()["id"])
    assert test_client.delete(f"/shops/{shop_with_config}/tags/{tag_id}").status_code == 204

    resp = test_client.post(f"/shops/{shop_with_config}/tags/{tag_id}/revisions/1/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert [r["kind"] for r in report["resurrected"]] == ["tag"]
    assert report["new_revision_no"] is not None
