"""Tests for /shops/{shop_id}/api-keys endpoints + the dual auth dependency."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from server.crud.crud_api_key import api_key_crud
from server.settings import app_settings
from tests.unit_tests.factories.api_key import make_api_key
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


# --- Per-shop scoping: a key minted for shop A must not reach shop B -------------------
#
# The key itself is valid (auth_required_any authenticates it fine); what is
# rejected is using it against a different shop's path. Enforced centrally by
# ``auth_required_any_for_shop``, wired as a router-level dependency on every
# ``/shops/{shop_id}/...`` router in ``server/api/api.py``.

SHOP_SCOPED_READ_PATHS = [
    "categories/",
    "products/",
    "products-to-tags/",
    "tags/",
    "attributes/",
    "attribute-options/",
    "product-attribute-values/",
    "revisions",
]


@pytest.mark.parametrize("path", SHOP_SCOPED_READ_PATHS)
def test_api_key_cannot_read_another_shop(real_auth_client, path):
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    _, plaintext = make_api_key(own_shop, name="scoped-reader")

    headers = {"X-API-Key": plaintext}
    assert real_auth_client.get(f"/shops/{own_shop}/{path}", headers=headers).status_code == 200
    forbidden = real_auth_client.get(f"/shops/{other_shop}/{path}", headers=headers)
    assert forbidden.status_code == 403, forbidden.text


def test_api_key_cannot_write_to_another_shop(real_auth_client):
    """Writes are rejected before the handler runs, so nothing is persisted."""
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    _, plaintext = make_api_key(own_shop, name="scoped-writer")

    resp = real_auth_client.post(
        f"/shops/{other_shop}/tags/",
        headers={"X-API-Key": plaintext},
        json={"shop_id": str(other_shop), "name": "smuggled"},
    )
    assert resp.status_code == 403, resp.text

    # And the tag really was not created.
    listing = real_auth_client.get(f"/shops/{other_shop}/tags/", headers={"X-API-Key": plaintext})
    assert listing.status_code == 403


# --- Per-shop scoping for Cognito users --------------------------------------------
#
# Same rule, other principal type: a user reaches shops whose UUID is one of their
# Cognito groups, or every shop if they are in an admin group.


def test_cognito_admin_reaches_any_shop(test_client):
    """The default stub token is in `admins`, so every shop stays reachable."""
    other_shop = make_shop(random_shop_name=True)
    assert test_client.get(f"/shops/{other_shop}/tags/").status_code == 200


def test_cognito_user_reaches_only_their_own_shop(as_cognito_user):
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    client = as_cognito_user([str(own_shop)])

    assert client.get(f"/shops/{own_shop}/tags/").status_code == 200
    assert client.get(f"/shops/{other_shop}/tags/").status_code == 403


def test_cognito_user_without_groups_is_refused(as_cognito_user):
    shop_id = make_shop(random_shop_name=True)
    client = as_cognito_user([])
    assert client.get(f"/shops/{shop_id}/tags/").status_code == 403


def test_mcp_client_token_is_scoped_like_a_user(fastapi_app, monkeypatch):
    """A token from the MCP app client is a person, not a service — scope it.

    ``auth_required`` already treats the MCP client id as a user token; the shop
    check must agree, or the agent login flow would reach every shop.
    """
    from server.security import auth_required, auth_required_any
    from tests.unit_tests.conftest import _cognito_token

    monkeypatch.setattr(app_settings, "AWS_COGNITO_MCP_CLIENT_ID", "mcp-client-id")
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)

    token = _cognito_token([str(own_shop)])
    token.client_id = "mcp-client-id"
    saved = {d: fastapi_app.dependency_overrides.get(d) for d in (auth_required, auth_required_any)}
    for dep in saved:
        fastapi_app.dependency_overrides[dep] = lambda: token
    try:
        client = TestClient(fastapi_app)
        assert client.get(f"/shops/{own_shop}/tags/").status_code == 200
        assert client.get(f"/shops/{other_shop}/tags/").status_code == 403
    finally:
        for dep, original in saved.items():
            fastapi_app.dependency_overrides[dep] = original


# --- API key management is itself shop-scoped ---------------------------------------
#
# Without this the per-shop key binding above is bypassable: mint a key *for* the
# shop you want and the binding is satisfied.


def test_cannot_mint_api_key_for_another_shop(as_cognito_user):
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    client = as_cognito_user([str(own_shop)])

    assert client.post(f"/shops/{own_shop}/api-keys/", json={"name": "mine"}).status_code == 201
    forbidden = client.post(f"/shops/{other_shop}/api-keys/", json={"name": "smuggled"})
    assert forbidden.status_code == 403, forbidden.text


def test_cannot_list_or_revoke_another_shops_api_keys(as_cognito_user):
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    victim_key, _ = make_api_key(other_shop, name="victim")
    client = as_cognito_user([str(own_shop)])

    assert client.get(f"/shops/{other_shop}/api-keys/").status_code == 403
    assert client.delete(f"/shops/{other_shop}/api-keys/{victim_key.id}").status_code == 403

    # The victim's key is untouched.
    still_active = api_key_crud.list_by_shop(other_shop)
    assert [r.id for r in still_active] == [victim_key.id]
    assert still_active[0].revoked_at is None
