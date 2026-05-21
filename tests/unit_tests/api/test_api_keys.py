"""Tests for /shops/{shop_id}/api-keys endpoints + the dual auth dependency."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.crud.crud_api_key import api_key_crud
from server.security import auth_required_any
from tests.unit_tests.factories.api_key import make_api_key
from tests.unit_tests.factories.shop import make_shop


@pytest.fixture
def real_auth_client(fastapi_app):
    """A TestClient whose ``auth_required_any`` override is removed so the
    real dual-auth dep runs (validates X-API-Key / Bearer headers against the
    DB). Other overrides — including the ``auth_required`` Cognito stub used
    by the api-key management endpoints — stay intact so we can still mint
    keys from the test."""
    override = fastapi_app.dependency_overrides.pop(auth_required_any, None)
    try:
        yield TestClient(fastapi_app)
    finally:
        if override is not None:
            fastapi_app.dependency_overrides[auth_required_any] = override


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


def test_api_key_opens_tagged_endpoint(real_auth_client):
    """End-to-end: a valid API key in X-API-Key opens an MCP-tagged route."""
    shop_id = make_shop()
    _, plaintext = make_api_key(shop_id, name="e2e")

    resp = real_auth_client.get(
        f"/shops/{shop_id}/tags/",
        headers={"X-API-Key": plaintext},
    )
    assert resp.status_code == 200, resp.text


def test_api_key_via_bearer_opens_tagged_endpoint(real_auth_client):
    """The dual-auth dep also accepts ``Authorization: Bearer sv_...``."""
    shop_id = make_shop()
    _, plaintext = make_api_key(shop_id, name="e2e-bearer")

    resp = real_auth_client.get(
        f"/shops/{shop_id}/tags/",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert resp.status_code == 200, resp.text


def test_bad_api_key_is_rejected(real_auth_client):
    shop_id = make_shop()
    resp = real_auth_client.get(
        f"/shops/{shop_id}/tags/",
        headers={"X-API-Key": "sv_deadbeef_thisisnotvalid"},
    )
    assert resp.status_code == 401


def test_revoked_api_key_stops_opening_endpoints(real_auth_client):
    """A key that authenticates first then gets revoked must stop working."""
    shop_id = make_shop()
    row, plaintext = make_api_key(shop_id, name="will-revoke")

    headers = {"X-API-Key": plaintext}
    assert real_auth_client.get(f"/shops/{shop_id}/tags/", headers=headers).status_code == 200

    api_key_crud.revoke(shop_id=shop_id, key_id=row.id)
    assert real_auth_client.get(f"/shops/{shop_id}/tags/", headers=headers).status_code == 401
