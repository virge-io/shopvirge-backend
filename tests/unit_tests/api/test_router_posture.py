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
"""Pin the auth posture of every route on the routers that were split by posture.

``shops.py``, ``orders.py`` and ``faq.py`` each used to be one router mixing
public reads with authenticated writes, so the guard was repeated per route and
a new route shipped unauthenticated if its author forgot. They are now split
into single-posture routers whose guard is declared at the mount in
``server/api/api.py``; these tests are what stops a route from silently moving
between them.

``test_endpoint_auth`` in test_authentication.py only sweeps paths ending in
``/`` and skips several of these, so none of them had coverage before.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

SHOP_ID = str(uuid.uuid4())
ID = str(uuid.uuid4())

PROTECTED = [
    # shops
    ("GET", "/shops/"),
    ("GET", "/shops/my-shops"),
    ("POST", "/shops/"),
    ("PUT", f"/shops/{SHOP_ID}"),
    ("DELETE", f"/shops/{SHOP_ID}"),
    ("PUT", f"/shops/config/{SHOP_ID}"),
    ("GET", f"/shops/allowed-ips/{SHOP_ID}"),
    ("POST", f"/shops/allowed-ips/{SHOP_ID}"),
    ("POST", f"/shops/allowed-ips/{SHOP_ID}/remove"),
    # orders
    ("GET", "/orders/"),
    ("GET", f"/orders/shop/{SHOP_ID}/pending"),
    ("GET", f"/orders/shop/{SHOP_ID}/complete"),
    ("PUT", f"/orders/{ID}"),
    ("DELETE", f"/orders/{ID}"),
    # faq
    ("POST", "/faq/"),
    ("PUT", f"/faq/{ID}"),
    ("DELETE", f"/faq/{ID}"),
]

PUBLIC = [
    # shops: storefront cache-invalidation polling, before anyone signs in
    ("GET", f"/shops/cache-status/{SHOP_ID}"),
    ("GET", f"/shops/last-completed-order/{SHOP_ID}"),
    ("GET", f"/shops/last-pending-order/{SHOP_ID}"),
    ("GET", f"/shops/{SHOP_ID}"),
    ("GET", f"/shops/config/{SHOP_ID}"),
    # orders: the checkout / POS flow
    ("GET", f"/orders/{ID}"),
    ("GET", f"/orders/check/{ID}"),
    ("POST", "/orders/"),
    ("PATCH", f"/orders/{ID}"),
    ("GET", f"/orders/stock/{ID}"),
    # faq: public content
    ("GET", "/faq/"),
    ("GET", f"/faq/{ID}"),
]


@pytest.mark.parametrize("method, path", PROTECTED)
def test_protected_routes_require_a_token(fastapi_app_not_authenticated, method, path):
    response = TestClient(fastapi_app_not_authenticated).request(method, path)
    assert response.status_code == 401, f"{method} {path} responded {response.status_code}, not 401"


@pytest.mark.parametrize("method, path", PUBLIC)
def test_public_routes_stay_reachable_without_a_token(fastapi_app_not_authenticated, method, path):
    response = TestClient(fastapi_app_not_authenticated).request(method, path)
    assert response.status_code != 401, f"{method} {path} responded 401 but is meant to be public"
