from unittest import mock
from uuid import UUID, uuid4

from server.db import db
from server.db.models import ProductTable

SIGNED = {"url": "https://bucket.s3.amazonaws.com/", "fields": {"key": "k", "policy": "p"}}


def test_create_upload_signs_fresh_key_per_call(shop_with_config, product, test_client):
    with mock.patch(
        "server.api.endpoints.products.image_uploads.create_presigned_post_url", return_value=SIGNED
    ) as sign:
        first = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/images/2/upload-url", json={"content_type": "image/png"}
        )
        second = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/images/2/upload-url", json={"content_type": "image/png"}
        )
    assert first.status_code == 201, first.json()
    body = first.json()
    assert body["url"] == SIGNED["url"] and body["fields"] == SIGNED["fields"]
    assert body["key"].startswith(f"{shop_with_config}/{product}-2-") and body["key"].endswith(".png")
    assert second.json()["key"] != body["key"]

    args, kwargs = sign.call_args
    assert args[0] == UUID(str(shop_with_config))
    assert kwargs["fields"] == {"Content-Type": "image/png"}
    assert ["content-length-range", 1, 10 * 1024 * 1024] in kwargs["conditions"]


def test_create_upload_rejects_unsupported_type_and_slot(shop_with_config, product, test_client):
    url = f"/shops/{shop_with_config}/products/{product}/images"
    assert test_client.post(f"{url}/1/upload-url", json={"content_type": "image/svg+xml"}).status_code == 422
    assert test_client.post(f"{url}/7/upload-url", json={"content_type": "image/png"}).status_code == 422


def test_create_upload_unknown_product(shop_with_config, test_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/products/{uuid4()}/images/1/upload-url", json={"content_type": "image/png"}
    )
    assert resp.status_code == 404


def test_create_upload_signing_failure(shop_with_config, product, test_client):
    with mock.patch("server.api.endpoints.products.image_uploads.create_presigned_post_url", return_value=None):
        resp = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/images/1/upload-url", json={"content_type": "image/png"}
        )
    assert resp.status_code == 502


def test_empty_string_clears_slot_to_null(shop_with_config, product, test_client):
    url = f"/shops/{shop_with_config}/products/{product}"
    assert test_client.put(url, json={"image_3": f"{shop_with_config}/x.png"}).status_code == 201
    assert test_client.put(url, json={"image_3": ""}).status_code == 201

    db.session.expire_all()
    assert db.session.query(ProductTable).filter_by(id=UUID(str(product))).one().image_3 is None
