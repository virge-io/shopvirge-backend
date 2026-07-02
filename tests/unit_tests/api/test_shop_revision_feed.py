"""Tests for the shop-wide revision feed and tag/attribute entity revisions."""

from server.db import db
from server.db.models import RevisionTable
from server.utils.json import json_dumps
from tests.unit_tests.api.test_product_revisions import product_body, product_category_id
from tests.unit_tests.factories.attribute import make_attribute, make_option
from tests.unit_tests.factories.tag import make_tag


def entity_revisions(entity_type, entity_id):
    return (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == entity_type, RevisionTable.entity_id == entity_id)
        .order_by(RevisionTable.revision_no)
        .all()
    )


def tag_body(shop_id, name):
    return {"shop_id": str(shop_id), "name": name, "translation": {"main_name": name}}


# --- Tag entity revisions ---


def test_tag_lifecycle_records_revisions(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(tag_body(shop, "summer")))
    assert resp.status_code == 201, resp.text
    tag_id = resp.json()["id"]

    resp = test_client.put(f"/shops/{shop}/tags/{tag_id}", content=json_dumps(tag_body(shop, "winter")))
    assert resp.status_code == 201, resp.text

    assert test_client.delete(f"/shops/{shop}/tags/{tag_id}").status_code == 204

    rows = entity_revisions("tag", tag_id)
    assert [r.action for r in rows] == ["create", "update", "delete"]
    assert rows[0].data["tag"]["name"] == "summer"
    assert rows[1].data["tag"]["name"] == "winter"
    assert rows[1].data["translation"]["main_name"] == "winter"
    # The delete revision snapshots the pre-delete state, so a rename can be recovered from it
    assert rows[2].data["tag"]["name"] == "winter"
    assert rows[0].created_by == "cognito:5678"


def test_legacy_tag_rename_gets_baseline(shop_with_config, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="old-name")

    body = {"shop_id": str(shop_with_config), "name": "new-name", "translation": {"main_name": "new-name"}}
    resp = test_client.put(f"/shops/{shop_with_config}/tags/{tag_id}", content=json_dumps(body))
    assert resp.status_code == 201, resp.text

    rows = entity_revisions("tag", tag_id)
    assert [r.action for r in rows] == ["baseline", "update"]
    assert rows[0].data["translation"]["main_name"] == "old-name"
    assert rows[0].created_by is None


# --- Attribute (incl. options) entity revisions ---


def test_attribute_and_option_mutations_record_revisions(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/attributes/", json={"name": "color", "unit": None})
    assert resp.status_code == 201, resp.text
    attr_id = resp.json()["id"]

    resp = test_client.post(f"/shops/{shop}/attribute-options/", json={"attribute_id": attr_id, "value_key": "RED"})
    assert resp.status_code == 201, resp.text
    option_id = resp.json()["id"]

    resp = test_client.put(f"/shops/{shop}/attribute-options/{option_id}", json={"value_key": "CRIMSON"})
    assert resp.status_code == 200, resp.text

    assert test_client.delete(f"/shops/{shop}/attribute-options/{option_id}").status_code == 204

    rows = entity_revisions("attribute", attr_id)
    assert [r.action for r in rows] == ["create", "update", "update", "update"]
    assert rows[0].data["attribute"]["name"] == "color"
    assert rows[0].data["options"] == []
    assert rows[1].data["options"] == [{"id": option_id, "value_key": "RED"}]
    assert rows[2].data["options"] == [{"id": option_id, "value_key": "CRIMSON"}]
    # Soft-deleted options disappear from the snapshot
    assert rows[3].data["options"] == []


def test_legacy_attribute_gets_baseline_with_existing_options(shop_with_config, test_client):
    attr_id = make_attribute(shop_with_config, name="size")
    make_option(attr_id, "XL")

    resp = test_client.post(
        f"/shops/{shop_with_config}/attribute-options/", json={"attribute_id": str(attr_id), "value_key": "XXL"}
    )
    assert resp.status_code == 201, resp.text

    rows = entity_revisions("attribute", attr_id)
    assert [r.action for r in rows] == ["baseline", "update"]
    assert [o["value_key"] for o in rows[0].data["options"]] == ["XL"]
    assert [o["value_key"] for o in rows[1].data["options"]] == ["XL", "XXL"]


def test_attribute_delete_records_revision(shop_with_config, test_client):
    attr_id = make_attribute(shop_with_config, name="doomed-attr")
    assert test_client.delete(f"/shops/{shop_with_config}/attributes/{attr_id}").status_code == 204

    rows = entity_revisions("attribute", attr_id)
    assert rows[-1].action == "delete"
    assert rows[-1].data["attribute"]["name"] == "doomed-attr"


# --- Shop-wide feed ---


def test_feed_lists_all_entity_types(shop_with_config, product, test_client):
    # Product edit (legacy product → baseline + update)
    category = product_category_id(product)
    body = product_body(shop_with_config, category, main_name="Feed product")
    assert test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body)).status_code == 201
    # Tag create
    assert (
        test_client.post(
            f"/shops/{shop_with_config}/tags/", content=json_dumps(tag_body(shop_with_config, "feed-tag"))
        ).status_code
        == 201
    )
    # Attribute create
    assert test_client.post(f"/shops/{shop_with_config}/attributes/", json={"name": "feed-attr"}).status_code == 201

    resp = test_client.get(f"/shops/{shop_with_config}/revisions")
    assert resp.status_code == 200, resp.text
    feed = resp.json()
    assert {item["entity_type"] for item in feed} == {"product", "tag", "attribute"}
    assert len(feed) == 4  # product baseline + product update + tag create + attribute create
    assert resp.headers["Content-Range"] == "revisions 0-3/4"
    # Every entry carries a human-readable name
    names = {item["name"] for item in feed}
    assert {"Feed product", "feed-tag", "feed-attr"} <= names
    # Newest first per entity: the product update outranks its baseline
    product_entries = [item for item in feed if item["entity_type"] == "product"]
    assert [e["revision_no"] for e in product_entries] == [2, 1]


def test_feed_filters(shop_with_config, test_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/tags/", content=json_dumps(tag_body(shop_with_config, "filter-tag"))
    )
    tag_id = resp.json()["id"]
    body = tag_body(shop_with_config, "filter-tag-renamed")
    assert test_client.put(f"/shops/{shop_with_config}/tags/{tag_id}", content=json_dumps(body)).status_code == 201

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?entity_type=tag")
    assert [item["action"] for item in resp.json()] == ["update", "create"]

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?entity_type=tag&action=create")
    assert [item["name"] for item in resp.json()] == ["filter-tag"]

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?entity_id={tag_id}")
    assert len(resp.json()) == 2

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?source=mcp")
    assert resp.json() == []

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?created_by=cognito:5678")
    assert len(resp.json()) == 2

    assert test_client.get(f"/shops/{shop_with_config}/revisions?entity_type=bogus").status_code == 422


def test_feed_pagination(shop_with_config, test_client):
    for i in range(3):
        resp = test_client.post(
            f"/shops/{shop_with_config}/tags/", content=json_dumps(tag_body(shop_with_config, f"page-tag-{i}"))
        )
        assert resp.status_code == 201

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?limit=2")
    assert len(resp.json()) == 2
    assert resp.headers["Content-Range"] == "revisions 0-1/3"

    resp = test_client.get(f"/shops/{shop_with_config}/revisions?skip=2&limit=2")
    assert len(resp.json()) == 1
    assert resp.headers["Content-Range"] == "revisions 2-2/3"


def test_feed_is_shop_scoped_and_detail_matches(shop, shop_with_config, test_client):
    resp = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(tag_body(shop, "mine")))
    assert resp.status_code == 201

    feed = test_client.get(f"/shops/{shop}/revisions").json()
    assert [item["name"] for item in feed] == ["mine"]
    # The other shop's feed does not contain it
    other_feed = test_client.get(f"/shops/{shop_with_config}/revisions").json()
    assert other_feed == []

    # Detail by revision id, shop-scoped
    revision_id = feed[0]["id"]
    detail = test_client.get(f"/shops/{shop}/revisions/{revision_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["tag"]["name"] == "mine"
    assert test_client.get(f"/shops/{shop_with_config}/revisions/{revision_id}").status_code == 404
