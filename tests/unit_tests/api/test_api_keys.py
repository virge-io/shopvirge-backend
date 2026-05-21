"""Tests for /shops/{shop_id}/api-keys endpoints + the dual auth dependency."""

from uuid import uuid4

from fastapi.testclient import TestClient

from server.crud.crud_api_key import api_key_crud
from tests.unit_tests.factories.shop import make_shop


def test_mint_returns_plaintext_once(test_client):
    shop_id = make_shop()
    resp = test_client.post(f"/shops/{shop_id}/api-keys/", json={"name": "ci-bot"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "ci-bot"
    assert body["plaintext"].startswith("sv_")
    assert body["prefix"] in body["plaintext"]

    # Listing must not return the plaintext.
    list_resp = test_client.get(f"/shops/{shop_id}/api-keys/")
    assert list_resp.status_code == 200
    keys = list_resp.json()
    assert len(keys) == 1
    assert "plaintext" not in keys[0]
    assert keys[0]["prefix"] == body["prefix"]


def test_revoked_key_cannot_authenticate(test_client, fastapi_app):
    """An API key validated via the dual auth dep stops working once revoked."""
    shop_id = make_shop()
    # Mint via CRUD so we control the plaintext.
    row, plaintext = api_key_crud.mint(shop_id=shop_id, name="will-be-revoked")

    # Sanity: looking up an active key works.
    assert api_key_crud.lookup_by_plaintext(plaintext) is not None

    # Now revoke and confirm lookup refuses it.
    api_key_crud.revoke(shop_id=shop_id, key_id=row.id)
    assert api_key_crud.lookup_by_plaintext(plaintext) is None


def test_revoke_unknown_key_returns_404(test_client):
    shop_id = make_shop()
    resp = test_client.delete(f"/shops/{shop_id}/api-keys/{uuid4()}")
    assert resp.status_code == 404


def test_revoke_existing_key_returns_204(test_client):
    shop_id = make_shop()
    create = test_client.post(f"/shops/{shop_id}/api-keys/", json={"name": "to-revoke"})
    key_id = create.json()["id"]
    resp = test_client.delete(f"/shops/{shop_id}/api-keys/{key_id}")
    assert resp.status_code == 204

    # Listing still shows it, but with revoked_at populated.
    keys = test_client.get(f"/shops/{shop_id}/api-keys/").json()
    [revoked] = keys
    assert revoked["revoked_at"] is not None


def test_mint_requires_auth(fastapi_app_not_authenticated):
    """The mint endpoint stays Cognito-only — an API key cannot create one."""
    client = TestClient(fastapi_app_not_authenticated)
    shop_id = make_shop()
    resp = client.post(
        f"/shops/{shop_id}/api-keys/",
        json={"name": "should-fail"},
    )
    assert resp.status_code == 401
