# Copyright 2026 René Dohmen <acidjunk@gmail.com>
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
"""The admin shop-type route, and the trial a new shop starts as until that route provisions its plan."""

from http import HTTPStatus
from uuid import uuid4

from server.db import ShopTable, db
from server.schemas.shop import ShopType
from tests.unit_tests.factories.shop import make_shop

PRODUCTION = {
    "name": "small",
    "max_languages": 3,
    "max_products": 0,
    "stripe_access": True,
    "trial_mode": False,
    "trial_started": "2026-10-01T12:00:00Z",
}


def _stored(shop_id) -> ShopType:
    db.session.expire_all()
    return ShopType(**db.session.get(ShopTable, shop_id).shop_type)


def test_admin_sets_the_shop_type(test_client, shop_with_config):
    response = test_client.put(f"/shops/{shop_with_config}/shop-type", json=PRODUCTION)

    assert response.status_code == HTTPStatus.OK, response.json()
    assert ShopType(**response.json()) == ShopType(**PRODUCTION)
    assert _stored(shop_with_config) == ShopType(**PRODUCTION)
    # the storefront reads it back from the public config route
    config = test_client.get(f"/shops/config/{shop_with_config}")
    assert config.status_code == HTTPStatus.OK
    assert ShopType(**config.json()["shop_type"]) == ShopType(**PRODUCTION)


def test_trial_started_may_be_left_out(test_client, shop):
    response = test_client.put(
        f"/shops/{shop}/shop-type", json={k: v for k, v in PRODUCTION.items() if k != "trial_started"}
    )

    assert response.status_code == HTTPStatus.OK, response.json()
    assert response.json()["trial_started"] is None


def test_member_may_not_set_the_shop_type(as_cognito_user):
    shop_id = make_shop(random_shop_name=True)
    client = as_cognito_user([str(shop_id)])

    response = client.put(f"/shops/{shop_id}/shop-type", json=PRODUCTION)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _stored(shop_id) == ShopType.trial()


def test_unknown_shop_is_404(test_client):
    assert test_client.put(f"/shops/{uuid4()}/shop-type", json=PRODUCTION).status_code == HTTPStatus.NOT_FOUND


def test_unknown_plan_name_is_rejected(test_client, shop):
    response = test_client.put(f"/shops/{shop}/shop-type", json=PRODUCTION | {"name": "enterprise"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _stored(shop) == ShopType.trial()


def test_new_shop_starts_as_a_trial_the_storefront_can_read(test_client, shop_with_config):
    """``make_shop`` mirrors ``POST /shops``: both give a shop the trial type (``test_shop_create`` covers the route)."""
    response = test_client.get(f"/shops/config/{shop_with_config}")

    assert response.status_code == HTTPStatus.OK
    assert ShopType(**response.json()["shop_type"]) == ShopType.trial()
