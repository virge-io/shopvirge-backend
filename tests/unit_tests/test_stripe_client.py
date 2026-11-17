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
"""Unit tests for the Stripe service helper.

These tests are intentionally pure-Python — no DB or HTTP — they
exercise key resolution and customer helpers against light
stubs so they stay fast and isolated from the rest of the suite.
"""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import stripe

from server.services import stripe_client
from server.services.stripe_client import (
    StripeCustomerMissing,
    StripeNotConfigured,
    get_api_key,
    get_client,
    get_customer_id,
    is_missing_customer_error,
)


def _shop(secret_key):
    return SimpleNamespace(id=uuid4(), stripe_secret_key=secret_key)


def _account(details):
    return SimpleNamespace(id=uuid4(), details=details)


def test_get_api_key_returns_each_shop_key_without_changing_global(monkeypatch):
    monkeypatch.setattr(stripe, "api_key", "sk_test_existing_global")
    assert get_api_key(_shop("sk_test_shop_a")) == "sk_test_shop_a"
    assert get_api_key(_shop("sk_test_shop_b")) == "sk_test_shop_b"
    assert stripe.api_key == "sk_test_existing_global"


@pytest.mark.parametrize("shop", [None, _shop(None), _shop("")])
def test_get_api_key_rejects_unconfigured_shop_without_changing_global(shop, monkeypatch):
    monkeypatch.setattr(stripe, "api_key", "sk_test_existing_global")
    with pytest.raises(StripeNotConfigured, match="has no stripe_secret_key configured"):
        get_api_key(shop)
    assert stripe.api_key == "sk_test_existing_global"


@pytest.mark.parametrize("shop", [None, _shop(None), _shop("")])
def test_get_client_rejects_unconfigured_shop(shop):
    with pytest.raises(StripeNotConfigured):
        get_client(shop)


def test_clients_keep_separate_keys_without_changing_global(monkeypatch):
    authorizations = []
    monkeypatch.setattr(stripe, "api_key", "sk_test_global")

    def request(self, method, url, headers, post_data=None):
        authorizations.append(headers["Authorization"])
        return json.dumps({"id": "cus_offline", "object": "customer"}), 200, {}

    monkeypatch.setattr(stripe.RequestsClient, "request", request)
    client_a = get_client(_shop("sk_test_a"))
    client_b = get_client(_shop("sk_test_b"))
    assert stripe.api_key == "sk_test_global"
    monkeypatch.setattr(stripe, "api_key", "sk_test_changed_global")
    client_a.customers.retrieve("cus_offline")
    client_b.customers.retrieve("cus_offline")
    client_a.customers.retrieve("cus_offline")
    assert authorizations == ["Bearer sk_test_a", "Bearer sk_test_b", "Bearer sk_test_a"]
    assert stripe.api_key == "sk_test_changed_global"


def test_client_keeps_bounded_timeout_and_network_retry(monkeypatch):
    timeouts = []
    retries = []

    def request_with_retries(method, url, headers, post_data=None, max_network_retries=None, **kwargs):
        retries.append(max_network_retries)
        return json.dumps({"id": "cus_offline", "object": "customer"}), 200, {}

    transport = SimpleNamespace(name="offline", request_with_retries=request_with_retries)
    monkeypatch.setattr(stripe, "new_default_http_client", lambda **kwargs: timeouts.append(kwargs) or transport)
    get_client(_shop("sk_test_timeout")).customers.retrieve("cus_offline")
    assert timeouts == [{"timeout": 20}]
    assert retries == [1]


def test_get_customer_id_returns_value():
    account = _account({"stripe_customer_id": "cus_abc"})
    assert get_customer_id(account) == "cus_abc"


def test_get_customer_id_raises_when_details_none():
    with pytest.raises(StripeCustomerMissing):
        get_customer_id(_account(None))


def test_get_customer_id_raises_when_key_absent():
    with pytest.raises(StripeCustomerMissing):
        get_customer_id(_account({}))


def test_get_customer_id_raises_when_value_empty():
    with pytest.raises(StripeCustomerMissing):
        get_customer_id(_account({"stripe_customer_id": ""}))


def test_is_missing_customer_error_matches_only_customer_resource_missing_errors():
    assert is_missing_customer_error(
        stripe.error.InvalidRequestError("No such customer", "customer", code="resource_missing")
    )
    assert not is_missing_customer_error(
        stripe.error.InvalidRequestError("No such product", "product", code="resource_missing")
    )


def test_fetch_customer_returns_dict(monkeypatch):
    monkeypatch.setattr(stripe, "api_key", "sk_test_global")
    shop = _shop("sk_test_fetch")
    fake_customer = SimpleNamespace(to_dict_recursive=lambda: {"id": "cus_xyz", "email": "x@example.com"})
    monkeypatch.setattr(
        stripe_client.stripe.CustomerService,
        "retrieve",
        lambda self, resource_id, params=None, options=None: fake_customer,
    )
    result = stripe_client.fetch_customer(shop, "cus_xyz")
    assert result == {"id": "cus_xyz", "email": "x@example.com"}
    assert stripe.api_key == "sk_test_global"


def test_fetch_customer_falls_back_to_dict_when_no_recursive(monkeypatch):
    shop = _shop("sk_test_fallback")

    class _FakeCustomer:
        def __iter__(self):
            return iter([("id", "cus_fallback"), ("email", "f@example.com")])

    monkeypatch.setattr(
        stripe_client.stripe.CustomerService,
        "retrieve",
        lambda self, resource_id, params=None, options=None: _FakeCustomer(),
    )
    result = stripe_client.fetch_customer(shop, "cus_fallback")
    assert result == {"id": "cus_fallback", "email": "f@example.com"}
