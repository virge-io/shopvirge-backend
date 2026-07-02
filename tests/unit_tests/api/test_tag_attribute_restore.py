"""Tests for restoring tags and attributes: by revision and from the trash."""

from uuid import UUID

from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable, ProductToTagTable, TagTable
from server.utils.json import json_dumps
from tests.unit_tests.api.test_shop_revision_feed import entity_revisions, tag_body
from tests.unit_tests.factories.attribute import make_attribute, make_option
from tests.unit_tests.factories.tag import make_tag


def get_tag(tag_id):
    db.session.expire_all()
    return db.session.query(TagTable).filter_by(id=tag_id).execution_options(include_deleted=True).one()


def get_attribute(attribute_id):
    db.session.expire_all()
    return db.session.query(AttributeTable).filter_by(id=attribute_id).execution_options(include_deleted=True).one()


def live_option_keys(attribute_id):
    db.session.expire_all()
    options = db.session.query(AttributeOptionTable).filter_by(attribute_id=attribute_id).all()
    return sorted(option.value_key for option in options)


# --- Tags ---


def test_restore_tag_revision_undoes_rename(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(tag_body(shop, "good-name")))
    tag_id = resp.json()["id"]
    body = tag_body(shop, "llm-mess")
    assert test_client.put(f"/shops/{shop}/tags/{tag_id}", content=json_dumps(body)).status_code == 201

    resp = test_client.post(f"/shops/{shop}/tags/{tag_id}/revisions/1/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["entity_type"] == "tag"
    assert report["restored_from_revision_no"] == 1

    tag = get_tag(tag_id)
    assert tag.name == "good-name"
    assert tag.translation.main_name == "good-name"
    assert entity_revisions("tag", UUID(tag_id))[-1].action == "restore"


def test_restore_tag_from_trash_brings_back_product_links(shop_with_config, product, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="linked-tag")
    test_client.post(
        f"/shops/{shop_with_config}/products-to-tags/",
        json={"product_id": str(product), "tag_id": str(tag_id), "shop_id": str(shop_with_config)},
    )
    assert test_client.delete(f"/shops/{shop_with_config}/tags/{tag_id}").status_code == 204
    assert get_tag(tag_id).deleted_at is not None

    resp = test_client.post(f"/shops/{shop_with_config}/tags/{tag_id}/restore")
    assert resp.status_code == 200, resp.json()
    assert [r["kind"] for r in resp.json()["resurrected"]] == ["tag"]

    assert get_tag(tag_id).deleted_at is None
    links = db.session.query(ProductToTagTable).filter_by(product_id=product).all()
    assert [link.tag_id for link in links] == [tag_id]


def test_restore_purged_tag_requires_force(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/tags/", content=json_dumps(tag_body(shop, "purge-me")))
    tag_id = resp.json()["id"]
    assert test_client.delete(f"/shops/{shop}/tags/{tag_id}?force=true").status_code == 204

    # Trash restore: gone
    assert test_client.post(f"/shops/{shop}/tags/{tag_id}/restore").status_code == 404
    # Revision restore without force: 410
    assert test_client.post(f"/shops/{shop}/tags/{tag_id}/revisions/1/restore").status_code == 410

    # With force the tag is recreated under its original id
    resp = test_client.post(f"/shops/{shop}/tags/{tag_id}/revisions/1/restore?force=true")
    assert resp.status_code == 200, resp.json()
    assert any("recreated" in w for w in resp.json()["warnings"])
    tag = get_tag(tag_id)
    assert tag.name == "purge-me"
    assert tag.translation.main_name == "purge-me"


# --- Attributes ---


def test_restore_attribute_revision_restores_option_set(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/attributes/", json={"name": "size", "unit": "EU"})
    attr_id = resp.json()["id"]
    for value_key in ("S", "M"):
        assert (
            test_client.post(
                f"/shops/{shop}/attribute-options/", json={"attribute_id": attr_id, "value_key": value_key}
            ).status_code
            == 201
        )
    good_revision_no = entity_revisions("attribute", UUID(attr_id))[-1].revision_no

    # The mess: rename the attribute, trash option M, add option XXL
    resp = test_client.put(f"/shops/{shop}/attributes/{attr_id}", json={"name": "sizz", "unit": None})
    assert resp.status_code == 200, resp.text
    m_option = db.session.query(AttributeOptionTable).filter_by(value_key="M").one()
    assert test_client.delete(f"/shops/{shop}/attribute-options/{m_option.id}").status_code == 204
    assert (
        test_client.post(
            f"/shops/{shop}/attribute-options/", json={"attribute_id": attr_id, "value_key": "XXL"}
        ).status_code
        == 201
    )
    assert live_option_keys(attr_id) == ["S", "XXL"]

    resp = test_client.post(f"/shops/{shop}/attributes/{attr_id}/revisions/{good_revision_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    # M was resurrected from the trash, XXL moved to the trash
    assert any(r["kind"] == "attribute_option" and r["name"] == "M" for r in report["resurrected"])
    assert any("XXL" in w and "trash" in w for w in report["warnings"])

    attribute = get_attribute(attr_id)
    assert attribute.name == "size"
    assert attribute.unit == "EU"
    assert live_option_keys(attr_id) == ["S", "M"] or live_option_keys(attr_id) == sorted(["S", "M"])
    assert entity_revisions("attribute", UUID(attr_id))[-1].action == "restore"


def test_restore_attribute_recreates_purged_option_with_same_id(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/attributes/", json={"name": "material"})
    attr_id = resp.json()["id"]
    resp = test_client.post(f"/shops/{shop}/attribute-options/", json={"attribute_id": attr_id, "value_key": "WOOL"})
    option_id = resp.json()["id"]
    snapshot_no = entity_revisions("attribute", UUID(attr_id))[-1].revision_no

    # Hard-purge the option
    assert test_client.delete(f"/shops/{shop}/attribute-options/{option_id}?force=true").status_code == 204
    assert db.session.query(AttributeOptionTable).filter_by(id=option_id).first() is None

    resp = test_client.post(f"/shops/{shop}/attributes/{attr_id}/revisions/{snapshot_no}/restore")
    assert resp.status_code == 200, resp.json()
    assert any("WOOL" in w and "recreated" in w for w in resp.json()["warnings"])

    # Recreated under the original id, so old product snapshots referencing it resolve again
    recreated = db.session.query(AttributeOptionTable).filter_by(id=option_id).one()
    assert recreated.value_key == "WOOL"


def test_restore_attribute_from_trash(shop_with_config, test_client):
    attr_id = make_attribute(shop_with_config, name="trash-attr")
    make_option(attr_id, "A")
    assert test_client.delete(f"/shops/{shop_with_config}/attributes/{attr_id}").status_code == 204
    assert get_attribute(attr_id).deleted_at is not None

    resp = test_client.post(f"/shops/{shop_with_config}/attributes/{attr_id}/restore")
    assert resp.status_code == 200, resp.json()
    assert get_attribute(attr_id).deleted_at is None
    assert live_option_keys(attr_id) == ["A"]


def test_double_restore_is_idempotent(shop, test_client):
    resp = test_client.post(f"/shops/{shop}/attributes/", json={"name": "twice"})
    attr_id = resp.json()["id"]
    assert (
        test_client.post(
            f"/shops/{shop}/attribute-options/", json={"attribute_id": attr_id, "value_key": "X"}
        ).status_code
        == 201
    )
    snapshot_no = entity_revisions("attribute", UUID(attr_id))[-1].revision_no

    for _ in range(2):
        resp = test_client.post(f"/shops/{shop}/attributes/{attr_id}/revisions/{snapshot_no}/restore")
        assert resp.status_code == 200, resp.json()

    assert live_option_keys(attr_id) == ["X"]
    assert db.session.query(AttributeOptionTable).filter_by(attribute_id=attr_id).count() == 1


# --- Trash listing ---


def test_trash_lists_tags_and_attributes(shop_with_config, test_client):
    tag_id = make_tag(shop_id=shop_with_config, main_name="binned-tag")
    attr_id = make_attribute(shop_with_config, name="binned-attr")
    assert test_client.delete(f"/shops/{shop_with_config}/tags/{tag_id}").status_code == 204
    assert test_client.delete(f"/shops/{shop_with_config}/attributes/{attr_id}").status_code == 204

    trash = test_client.get(f"/shops/{shop_with_config}/trash").json()
    by_type = {(item["entity_type"], item["name"]) for item in trash}
    assert ("tag", "binned-tag") in by_type
    assert ("attribute", "binned-attr") in by_type
