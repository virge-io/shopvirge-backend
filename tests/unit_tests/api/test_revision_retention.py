"""Tests for revision retention pruning and its configuration."""

from server.db import db
from server.db.models import RevisionTable
from server.settings import app_settings
from server.utils.json import json_dumps
from tests.unit_tests.api.test_product_revisions import product_body, product_category_id, revision_rows


def _update_n_times(test_client, shop_id, product_id, category_id, n):
    for i in range(n):
        body = product_body(shop_id, category_id, main_name=f"Retention v{i}", price=float(i + 1))
        resp = test_client.put(f"/shops/{shop_id}/products/{product_id}", content=json_dumps(body))
        assert resp.status_code == 201, resp.json()


def test_retention_prunes_old_revisions(shop_with_config, product, test_client, monkeypatch):
    monkeypatch.setattr(app_settings, "REVISION_RETENTION", 12)
    category = product_category_id(product)

    _update_n_times(test_client, shop_with_config, product, category, 15)

    rows = revision_rows(product)
    assert len(rows) == 12
    # The highest, contiguous revision numbers survive
    assert [r.revision_no for r in rows] == list(range(4, 16))
    assert rows[-1].data["translation"]["main_name"] == "Retention v14"


def test_retention_never_drops_below_minimum(shop_with_config, product, test_client, monkeypatch):
    monkeypatch.setattr(app_settings, "REVISION_RETENTION", 3)  # below the floor of 10
    category = product_category_id(product)

    _update_n_times(test_client, shop_with_config, product, category, 12)

    rows = revision_rows(product)
    assert len(rows) == 10
    assert [r.revision_no for r in rows] == list(range(3, 13))
