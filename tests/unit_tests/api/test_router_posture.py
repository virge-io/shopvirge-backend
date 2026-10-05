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
"""Check the live route table against the auth posture declared in ``server/api/api.py``.

Auth is declared per tier there, not per route. The two public tiers (``public``
and ``shop_public``) carry no guard; every other tier, and each direct include,
carries one. So the set of public routes is not a list to maintain here: it is
whatever is mounted on those two tiers. The sweep sends every route a request
with no credentials and checks both directions.

* Not on a public tier: must answer 401. Catches a tier or direct include that
  lost its guard, a guard that bypasses ``current_principal`` (the resolver the
  fixture overrides), and a protected route shadowed by an earlier public one.
* On a public tier: must answer anything but 401. Catches a public module that
  grew a per-route guard, and a public route shadowed by an earlier protected one.

Intent is deliberately not pinned: moving a handler from a protected module into
a public one passes both checks. That move is a file change plus a router change,
which is what the one-posture-per-module layout makes reviewable.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.api import api

SAMPLE_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _operations(*routers) -> list[tuple[str, str]]:
    return sorted(
        {
            (method, route.path)
            for router in routers
            for route in router.routes
            if isinstance(route, APIRoute)
            for method in route.methods
        }
    )


PUBLIC_OPERATIONS = _operations(api.public, api.shop_public)
GUARDED_OPERATIONS = sorted(set(_operations(api.api_router)) - set(PUBLIC_OPERATIONS))


def _ids(operations):
    return [f"{method} {path}" for method, path in operations]


def _request_without_credentials(app, method, path):
    concrete = re.sub(r"\{[^}]+\}", SAMPLE_ID, path)
    # A public route may 500 on a made-up id, or on purpose (``/sentry/``). That is
    # still "not 401", which is all these tests are about.
    return TestClient(app, raise_server_exceptions=False).request(method, concrete)


def test_the_tiers_cover_the_whole_route_table():
    """Guards live on the tiers, so a route outside them is a route nobody guards."""
    assert len(PUBLIC_OPERATIONS) + len(GUARDED_OPERATIONS) == len(_operations(api.api_router))
    assert PUBLIC_OPERATIONS, "no public tier is mounted at all"


@pytest.mark.parametrize("method, path", GUARDED_OPERATIONS, ids=_ids(GUARDED_OPERATIONS))
def test_routes_off_the_public_tiers_answer_401_without_a_token(fastapi_app_not_authenticated, method, path):
    response = _request_without_credentials(fastapi_app_not_authenticated, method, path)
    assert response.status_code == 401, f"{method} {path} answered {response.status_code} without a token"


@pytest.mark.parametrize("method, path", PUBLIC_OPERATIONS, ids=_ids(PUBLIC_OPERATIONS))
def test_routes_on_the_public_tiers_answer_without_a_token(fastapi_app_not_authenticated, method, path):
    response = _request_without_credentials(fastapi_app_not_authenticated, method, path)
    assert response.status_code != 401, f"{method} {path} is on a public tier but answered 401"


def test_no_route_is_shadowed_by_an_earlier_one(fastapi_app_not_authenticated):
    """FastAPI matches routes in registration order, so a parameterised route
    registered before a more specific one swallows it (``GET /shops/{id}`` before
    ``GET /shops/my-shops`` would turn my-shops into a 422). api.py registers the
    auth tiers in a deliberate order; this pins that no route is unreachable.
    """
    routes = [r for r in fastapi_app_not_authenticated.routes if isinstance(r, APIRoute)]
    shadowed = []
    for index, route in enumerate(routes):
        concrete = re.sub(r"\{[^}]+\}", SAMPLE_ID, route.path)
        for earlier in routes[:index]:
            if (
                earlier.methods & route.methods
                and earlier.path != route.path
                and re.fullmatch(earlier.path_regex.pattern, concrete)
            ):
                shadowed.append(f"{sorted(route.methods)[0]} {route.path} is shadowed by {earlier.path}")
    assert not shadowed, "\n".join(shadowed)
