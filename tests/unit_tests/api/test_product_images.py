import base64
import socket
from unittest import mock
from uuid import UUID, uuid4

import httpx
import pytest

from server.db import db
from server.db.models import ProductTable, RevisionTable

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture()
def s3_client():
    client = mock.MagicMock()
    client.generate_presigned_url.return_value = "https://signed.example/preview"
    with mock.patch("server.api.endpoints.products.images._upload_s3_client", return_value=client):
        yield client


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def _row(product_id) -> ProductTable:
    db.session.expire_all()
    return db.session.query(ProductTable).filter_by(id=UUID(str(product_id))).one()


def test_upload_base64_sets_slot_and_records_revision(shop_with_config, product, test_client, s3_client):
    body = {"image_base64": "data:image/png;base64," + base64.b64encode(PNG).decode()}
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/images/2", json=body)
    assert resp.status_code == 201, resp.json()

    key = resp.json()["image_2"]
    assert key.startswith(f"{shop_with_config}/{product}-2-") and key.endswith(".png")
    assert resp.json()["preview_url"] == "https://signed.example/preview"
    s3_client.put_object.assert_called_once()
    assert s3_client.put_object.call_args.kwargs["ContentType"] == "image/png"
    assert s3_client.put_object.call_args.kwargs["Key"] == key
    assert _row(product).image_2 == key

    revisions = (
        db.session.query(RevisionTable)
        .filter(RevisionTable.entity_type == "product", RevisionTable.entity_id == product)
        .order_by(RevisionTable.revision_no)
        .all()
    )
    assert [r.action for r in revisions] == ["baseline", "update"]
    assert revisions[-1].data["product"]["image_2"] == key


def test_upload_url(shop_with_config, product, test_client, s3_client):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=JPEG))
    real_client = httpx.Client
    with (
        mock.patch("server.api.endpoints.products.images.socket.getaddrinfo", _public_dns),
        mock.patch(
            "server.api.endpoints.products.images.httpx.Client",
            lambda **kw: real_client(transport=transport, **kw),
        ),
    ):
        resp = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/images/1",
            json={"image_url": "https://images.example/shirt.jpg"},
        )
    assert resp.status_code == 201, resp.json()
    assert resp.json()["image_1"].endswith(".jpg")
    assert _row(product).image_1 == resp.json()["image_1"]


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/a.png", "http://127.0.0.1/a.png", "http://169.254.169.254/latest"],
)
def test_upload_url_refuses_non_public_targets(shop_with_config, product, test_client, s3_client, url):
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/images/1", json={"image_url": url})
    assert resp.status_code == 400, resp.json()
    s3_client.put_object.assert_not_called()


def test_upload_url_refuses_redirect_to_private_host(shop_with_config, product, test_client, s3_client):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://10.0.0.5/secret.png"})

    def dns(host, *_args, **_kwargs):
        ip = "10.0.0.5" if host == "10.0.0.5" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    real_client = httpx.Client
    with (
        mock.patch("server.api.endpoints.products.images.socket.getaddrinfo", dns),
        mock.patch(
            "server.api.endpoints.products.images.httpx.Client",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        ),
    ):
        resp = test_client.post(
            f"/shops/{shop_with_config}/products/{product}/images/1", json={"image_url": "http://evil.example/a"}
        )
    assert resp.status_code == 400, resp.json()
    s3_client.put_object.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"image_url": "https://a.example/x.png", "image_base64": base64.b64encode(PNG).decode()},
    ],
)
def test_upload_requires_exactly_one_source(shop_with_config, product, test_client, s3_client, body):
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/images/1", json=body)
    assert resp.status_code == 422


def test_upload_rejects_non_image(shop_with_config, product, test_client, s3_client):
    body = {"image_base64": base64.b64encode(b"<html>not an image</html>").decode()}
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/images/1", json=body)
    assert resp.status_code == 400
    s3_client.put_object.assert_not_called()


def test_upload_rejects_invalid_base64(shop_with_config, product, test_client, s3_client):
    resp = test_client.post(
        f"/shops/{shop_with_config}/products/{product}/images/1", json={"image_base64": "!!not base64!!"}
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("slot", [0, 7])
def test_upload_slot_out_of_range(shop_with_config, product, test_client, s3_client, slot):
    body = {"image_base64": base64.b64encode(PNG).decode()}
    resp = test_client.post(f"/shops/{shop_with_config}/products/{product}/images/{slot}", json=body)
    assert resp.status_code == 422


def test_upload_unknown_product(shop_with_config, test_client, s3_client):
    body = {"image_base64": base64.b64encode(PNG).decode()}
    resp = test_client.post(f"/shops/{shop_with_config}/products/{uuid4()}/images/1", json=body)
    assert resp.status_code == 404
    s3_client.put_object.assert_not_called()


def test_delete_image_clears_slot(shop_with_config, product, test_client, s3_client):
    body = {"image_base64": base64.b64encode(PNG).decode()}
    assert test_client.post(f"/shops/{shop_with_config}/products/{product}/images/3", json=body).status_code == 201

    resp = test_client.delete(f"/shops/{shop_with_config}/products/{product}/images/3")
    assert resp.status_code == 200, resp.json()
    assert not _row(product).image_3

    resp = test_client.delete(f"/shops/{shop_with_config}/products/{product}/images/3")
    assert resp.status_code == 404
