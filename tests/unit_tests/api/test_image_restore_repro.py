"""Regression: deleting images via update (the shop UI sends image_X: ''),
then restoring the with-images revision must bring the images back — both on
the product row and in the new restore revision's snapshot.
"""

from uuid import UUID

from server.db import db
from server.db.models import ProductTable, RevisionTable
from server.utils.json import json_dumps
from tests.unit_tests.api.test_product_revisions import product_body, product_category_id


def _revisions(product_id):
    return (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product_id)
        .order_by(RevisionTable.revision_no)
        .all()
    )


def test_restore_brings_deleted_images_back(shop_with_config, product, test_client):
    category = product_category_id(product)

    body_with_images = product_body(shop_with_config, category, main_name="Shirt", price=10.0)
    body_with_images["image_1"] = "shop-prefix/foo.png"
    body_with_images["image_2"] = "shop-prefix/bar.png"
    resp = test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body_with_images))
    assert resp.status_code == 201, resp.json()

    # Removed image slots arrive as empty strings from the shop UI
    body_removed = product_body(shop_with_config, category, main_name="Shirt", price=10.0)
    resp = test_client.put(f"/shops/{shop_with_config}/products/{product}", content=json_dumps(body_removed))
    assert resp.status_code == 201, resp.json()

    rows = _revisions(product)
    assert [r.action for r in rows] == ["baseline", "update", "update"]
    with_images_no = rows[1].revision_no
    assert rows[1].data["product"]["image_1"] == "shop-prefix/foo.png"
    assert not rows[2].data["product"]["image_1"]

    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/revisions/{with_images_no}/restore")
    assert resp.status_code == 200, resp.json()
    report = resp.json()
    assert report["restored"] is True
    assert report["skipped_fields"] == []

    db.session.expire_all()
    row = db.session.query(ProductTable).filter_by(id=UUID(str(product))).one()
    assert row.image_1 == "shop-prefix/foo.png"
    assert row.image_2 == "shop-prefix/bar.png"

    rows = _revisions(product)
    assert rows[-1].action == "restore"
    restore_snapshot = rows[-1].data["product"]
    assert restore_snapshot["image_1"] == "shop-prefix/foo.png"
    assert restore_snapshot["image_2"] == "shop-prefix/bar.png"
