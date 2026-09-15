# Copyright 2024 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the cross-shop admin accounts endpoints.

Stripe API calls are intercepted with ``monkeypatch.setattr`` against
``server.services.stripe_client.stripe.Customer.retrieve``. The helper
imports ``stripe`` at module scope so that path is the right injection
point — patching ``stripe.Customer.retrieve`` directly would also work
but bleeds across tests.
"""

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import stripe
from fastapi.testclient import TestClient

from server.db import db
from server.db.models import Account, ShopTable
from server.services import stripe_client
from tests.unit_tests.factories.account import make_account, make_account_with_stripe
from tests.unit_tests.factories.shop import make_shop


def _set_stripe_secret(shop_id, key="sk_test_secret"):
    shop = db.session.get(ShopTable, shop_id)
    shop.stripe_secret_key = key
    db.session.commit()


def _stripe_customer_obj(payload: dict):
    """Build a stripe-like object whose ``to_dict_recursive`` returns ``payload``."""
    return SimpleNamespace(to_dict_recursive=lambda: payload)


@pytest.fixture()
def shop_with_stripe(shop):
    _set_stripe_secret(shop)
    return shop


@pytest.fixture()
def account_with_stripe(shop_with_stripe):
    return make_account_with_stripe(
        shop_id=shop_with_stripe,
        name="Stripe-Linked Account",
        customer_id="cus_test_123",
    )


@pytest.fixture()
def account_no_stripe(shop):
    return make_account(shop_id=shop, name="No-Stripe Account", details={})


@pytest.fixture()
def account_no_secret_key():
    """Account whose shop has NO ``stripe_secret_key`` configured."""
    shop_id = make_shop(random_shop_name=True)
    return make_account_with_stripe(shop_id=shop_id, name="Orphaned Stripe Account", customer_id="cus_orphan_456")


# ---------------------------------------------------------------------------
# List + filter
# ---------------------------------------------------------------------------


def test_admin_accounts_list_cross_shop(test_client, account_with_stripe, account_no_stripe, account_no_secret_key):
    response = test_client.get("/admin/accounts?limit=200")
    assert response.status_code == 200
    payload = response.json()
    ids = {item["id"] for item in payload}
    assert str(account_with_stripe) in ids
    assert str(account_no_stripe) in ids
    assert str(account_no_secret_key) in ids
    # Each item exposes the convenience fields
    by_id = {item["id"]: item for item in payload}
    linked = by_id[str(account_with_stripe)]
    assert linked["stripe_customer_id"] == "cus_test_123"
    assert linked["shop_name"] is not None
    no_stripe = by_id[str(account_no_stripe)]
    assert no_stripe["stripe_customer_id"] is None


def test_admin_accounts_filter_by_shop_id(test_client, shop_with_stripe, account_with_stripe, account_no_secret_key):
    response = test_client.get(f"/admin/accounts?shop_id={shop_with_stripe}&limit=200")
    assert response.status_code == 200
    payload = response.json()
    ids = {item["id"] for item in payload}
    assert str(account_with_stripe) in ids
    assert str(account_no_secret_key) not in ids


def test_admin_accounts_filter_missing_stripe_true(test_client, account_with_stripe, account_no_stripe):
    response = test_client.get("/admin/accounts?missing_stripe=true&limit=200")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert str(account_no_stripe) in ids
    assert str(account_with_stripe) not in ids


def test_admin_accounts_filter_missing_stripe_false(test_client, account_with_stripe, account_no_stripe):
    response = test_client.get("/admin/accounts?missing_stripe=false&limit=200")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert str(account_with_stripe) in ids
    assert str(account_no_stripe) not in ids


def test_admin_accounts_list_sets_content_range_header(test_client, account_with_stripe):
    response = test_client.get("/admin/accounts?limit=10")
    assert response.status_code == 200
    assert "Content-Range" in response.headers


# ---------------------------------------------------------------------------
# Detail + 404
# ---------------------------------------------------------------------------


def test_admin_accounts_get_by_id(test_client, account_with_stripe):
    response = test_client.get(f"/admin/accounts/{account_with_stripe}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(account_with_stripe)
    assert body["stripe_customer_id"] == "cus_test_123"
    assert body["shop_name"] is not None


def test_admin_accounts_get_by_id_404(test_client):
    response = test_client.get(f"/admin/accounts/{uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Sync (persists)
# ---------------------------------------------------------------------------


def test_admin_accounts_sync_stripe_success(test_client, account_with_stripe, monkeypatch):
    fake_payload = {
        "id": "cus_test_123",
        "email": "synced@example.com",
        "name": "Synced Customer",
    }
    monkeypatch.setattr(
        stripe_client.stripe.Customer,
        "retrieve",
        lambda customer_id: _stripe_customer_obj(fake_payload),
    )

    response = test_client.post(f"/admin/accounts/{account_with_stripe}/sync-stripe")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(account_with_stripe)
    assert body["stripe_customer_id"] == "cus_test_123"
    assert body["stripe_customer"]["email"] == "synced@example.com"
    # ISO-8601 timestamp is parseable
    assert datetime.fromisoformat(body["stripe_synced_at"].replace("Z", ""))

    db.session.expire_all()
    refreshed = db.session.get(Account, account_with_stripe)
    assert refreshed.details["stripe_customer"]["email"] == "synced@example.com"
    assert "stripe_synced_at" in refreshed.details
    # Existing keys are preserved
    assert refreshed.details["stripe_customer_id"] == "cus_test_123"


def test_admin_accounts_sync_stripe_no_customer_id(test_client, account_no_stripe):
    response = test_client.post(f"/admin/accounts/{account_no_stripe}/sync-stripe")
    assert response.status_code == 400
    assert "stripe_customer_id" in response.json()["detail"]


def test_admin_accounts_sync_stripe_no_secret_key(test_client, account_no_secret_key):
    response = test_client.post(f"/admin/accounts/{account_no_secret_key}/sync-stripe")
    assert response.status_code == 400
    assert "stripe_secret_key" in response.json()["detail"]


def test_admin_accounts_sync_stripe_stripe_error(test_client, account_with_stripe, monkeypatch):
    def _raise(customer_id):
        raise stripe.error.InvalidRequestError("no such customer", "id")

    monkeypatch.setattr(stripe_client.stripe.Customer, "retrieve", _raise)
    response = test_client.post(f"/admin/accounts/{account_with_stripe}/sync-stripe")
    assert response.status_code == 502
    assert "stripe" in response.json()["detail"].lower()


def test_admin_accounts_sync_stripe_account_not_found(test_client):
    response = test_client.post(f"/admin/accounts/{uuid4()}/sync-stripe")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Read-through stripe customer (does NOT persist)
# ---------------------------------------------------------------------------


def test_admin_accounts_stripe_customer_readthrough(test_client, account_with_stripe, monkeypatch):
    fake_payload = {"id": "cus_test_123", "email": "readonly@example.com"}
    monkeypatch.setattr(
        stripe_client.stripe.Customer,
        "retrieve",
        lambda customer_id: _stripe_customer_obj(fake_payload),
    )

    response = test_client.get(f"/admin/accounts/{account_with_stripe}/stripe-customer")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["account_id"] == str(account_with_stripe)
    assert body["stripe_customer_id"] == "cus_test_123"
    assert body["stripe_customer"]["email"] == "readonly@example.com"

    db.session.expire_all()
    refreshed = db.session.get(Account, account_with_stripe)
    # Read-through must NOT have written the snapshot
    assert "stripe_customer" not in (refreshed.details or {})
    assert "stripe_synced_at" not in (refreshed.details or {})


def test_admin_accounts_stripe_customer_no_secret_key(test_client, account_no_secret_key):
    response = test_client.get(f"/admin/accounts/{account_no_secret_key}/stripe-customer")
    assert response.status_code == 400


def test_admin_accounts_stripe_customer_no_customer_id(test_client, account_no_stripe):
    response = test_client.get(f"/admin/accounts/{account_no_stripe}/stripe-customer")
    assert response.status_code == 400


def test_admin_accounts_stripe_customer_missing_from_stripe_returns_not_found(
    test_client, account_with_stripe, monkeypatch
):
    def _raise(customer_id):
        raise stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")

    monkeypatch.setattr(stripe_client.stripe.Customer, "retrieve", _raise)

    response = test_client.get(f"/admin/accounts/{account_with_stripe}/stripe-customer")

    assert response.status_code == 404
    assert "no longer exists" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Link (manual association)
# ---------------------------------------------------------------------------


def test_admin_accounts_link_stripe_success(test_client, account_no_stripe):
    response = test_client.post(
        f"/admin/accounts/{account_no_stripe}/link-stripe",
        json={"stripe_customer_id": "cus_manual_abc"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stripe_customer_id"] == "cus_manual_abc"

    db.session.expire_all()
    refreshed = db.session.get(Account, account_no_stripe)
    assert refreshed.details["stripe_customer_id"] == "cus_manual_abc"


def test_admin_accounts_link_stripe_404(test_client):
    response = test_client.post(
        f"/admin/accounts/{uuid4()}/link-stripe",
        json={"stripe_customer_id": "cus_x"},
    )
    assert response.status_code == 404


def test_admin_accounts_link_stripe_validation(test_client, account_no_stripe):
    response = test_client.post(
        f"/admin/accounts/{account_no_stripe}/link-stripe",
        json={},  # missing required field
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Auth: superuser dependency must reject anonymous callers
# ---------------------------------------------------------------------------


def test_admin_accounts_require_superuser(fastapi_app_not_authenticated, account_with_stripe):
    """No JWT → OAuth2 scheme returns 401 before the handler runs."""
    client = TestClient(fastapi_app_not_authenticated)
    assert client.get("/admin/accounts").status_code == 401
    assert client.get(f"/admin/accounts/{account_with_stripe}").status_code == 401
    assert client.post(f"/admin/accounts/{account_with_stripe}/sync-stripe").status_code == 401
    assert client.get(f"/admin/accounts/{account_with_stripe}/stripe-customer").status_code == 401
    assert (
        client.post(
            f"/admin/accounts/{account_with_stripe}/link-stripe",
            json={"stripe_customer_id": "cus_x"},
        ).status_code
        == 401
    )
