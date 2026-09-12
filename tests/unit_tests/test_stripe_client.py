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
exercise ``configure_for_shop`` and ``get_customer_id`` against light
stubs so they stay fast and isolated from the rest of the suite.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import stripe

from server.services import stripe_client
from server.services.stripe_client import (
    StripeCustomerMissing,
    StripeNotConfigured,
    configure_for_shop,
    get_customer_id,
    is_missing_customer_error,
)


def _shop(secret_key):
    return SimpleNamespace(id=uuid4(), stripe_secret_key=secret_key)


def _account(details):
    return SimpleNamespace(id=uuid4(), details=details)


def test_configure_for_shop_sets_api_key():
    shop = _shop("sk_test_configure")
    returned = configure_for_shop(shop)
    assert stripe.api_key == "sk_test_configure"
    assert returned is stripe


def test_configure_for_shop_raises_without_key():
    with pytest.raises(StripeNotConfigured):
        configure_for_shop(_shop(None))


def test_configure_for_shop_raises_for_empty_string_key():
    with pytest.raises(StripeNotConfigured):
        configure_for_shop(_shop(""))


def test_configure_for_shop_raises_when_shop_is_none():
    with pytest.raises(StripeNotConfigured):
        configure_for_shop(None)  # type: ignore[arg-type]


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
    shop = _shop("sk_test_fetch")
    fake_customer = SimpleNamespace(to_dict_recursive=lambda: {"id": "cus_xyz", "email": "x@example.com"})
    monkeypatch.setattr(stripe_client.stripe.Customer, "retrieve", lambda cid: fake_customer)
    result = stripe_client.fetch_customer(shop, "cus_xyz")
    assert result == {"id": "cus_xyz", "email": "x@example.com"}
    assert stripe.api_key == "sk_test_fetch"


def test_fetch_customer_falls_back_to_dict_when_no_recursive(monkeypatch):
    shop = _shop("sk_test_fallback")

    class _FakeCustomer:
        def __iter__(self):
            return iter([("id", "cus_fallback"), ("email", "f@example.com")])

    monkeypatch.setattr(stripe_client.stripe.Customer, "retrieve", lambda cid: _FakeCustomer())
    result = stripe_client.fetch_customer(shop, "cus_fallback")
    assert result == {"id": "cus_fallback", "email": "f@example.com"}
