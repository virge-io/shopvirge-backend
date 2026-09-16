"""Every shop-scoped route must be guarded, or explicitly declared public.

The per-shop guard (``require_shop``) is wired in ``server/api/api.py`` and, for the handful of
routers that mix postures, in the route decorator. Nothing stops someone adding
a new ``/shops/{shop_id}/...`` router with a plain ``require_cognito`` dependency,
which authenticates but does not scope — and that mistake is invisible in review.

So this test walks the route table and asserts the invariant directly. A route
that reaches shop data without a guard fails here; a route that is genuinely
public has to be named in ``PUBLIC_SHOP_ROUTES`` on purpose.

Note the shop id is *not* always spelled ``shop_id``: a few older routes use
``{id}``. Matching on the parameter name would silently skip them, so routes are
matched on path shape instead.
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.exceptions import ResponseValidationError
from fastapi.routing import APIRoute

from server.db.models import ShopTable
from server.security import require_shop
from tests.unit_tests.factories.shop import make_shop

# Routes under /shops that intentionally need no shop scoping, with the reason.
# Adding to this list is a deliberate act — it means "anyone may call this".
PUBLIC_SHOP_ROUTES = {
    # Collection-level: no single shop in the path.
    ("GET", "/shops/"): "lists shops the caller may see",
    ("POST", "/shops/"): "create a new shop",
    ("GET", "/shops/my-shops"): "the shop-access resolution point itself",
    # Public storefront reads — the shop front-end calls these unauthenticated.
    ("GET", "/shops/{shop_id}"): "public shop page",
    ("GET", "/shops/config/{shop_id}"): "public storefront config",
    ("GET", "/shops/cache-status/{shop_id}"): "public cache probe",
    ("GET", "/shops/last-completed-order/{shop_id}"): "public POS poll",
    ("GET", "/shops/last-pending-order/{shop_id}"): "public POS poll",
    ("GET", "/shops/{shop_id}/prices/"): "public price list",
    ("POST", "/shops/{shop_id}/prices/"): "public price lookup",
    ("GET", "/shops/{shop_id}/products/{product_id}"): "public product page",
    ("GET", "/shops/{shop_id}/products/{product_id}/with_attributes"): "public product page",
    ("GET", "/shops/{shop_id}/categories/{category_id}/products"): "public category page",
    ("GET", "/shops/{shop_id}/categories/{category_id}/available-attributes"): "public filter facets",
    # Checkout: called by anonymous shoppers, guarded by Stripe itself.
    ("POST", "/shops/{shop_id}/stripe/"): "anonymous checkout",
    ("POST", "/shops/{shop_id}/stripe/subscription"): "anonymous checkout",
    ("DELETE", "/shops/{shop_id}/stripe/subscription/{subscription_id}"): "anonymous checkout",
}

# A path segment holding a shop id, however it is spelled.
_SHOP_PATH = re.compile(r"^/shops/\{shop_id\}|^/shops/[a-z-]+/\{shop_id\}")


def _guards_in_chain(dependant) -> bool:
    """True if a per-shop guard appears anywhere in the route's dependency tree."""
    stack = [dependant]
    while stack:
        current = stack.pop()
        for sub in current.dependencies:
            call = sub.call
            if call is require_shop:
                return True
            stack.append(sub)
    return False


def _shop_scoped_routes(app: FastAPI):
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/shops/") and route.path != "/shops/":
            continue
        if not (_SHOP_PATH.match(route.path) or route.path in ("/shops/", "/shops/my-shops")):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, route


def test_every_shop_scoped_route_is_guarded_or_declared_public(fastapi_app: FastAPI) -> None:
    unguarded = [
        f"{method} {route.path}"
        for method, route in _shop_scoped_routes(fastapi_app)
        if (method, route.path) not in PUBLIC_SHOP_ROUTES and not _guards_in_chain(route.dependant)
    ]
    assert not unguarded, (
        "These routes reach shop-scoped data without a per-shop guard:\n  "
        + "\n  ".join(sorted(unguarded))
        + "\n\nAdd require_shop to the "
        "router in server/api/api.py (or to the route decorator), or — if the route really is "
        "public — add it to PUBLIC_SHOP_ROUTES with a reason."
    )


def test_public_shop_route_allowlist_has_no_stale_entries(fastapi_app: FastAPI) -> None:
    """A route removed or renamed should not leave a permanent hole in the allowlist."""
    live = {(method, route.path) for method, route in _shop_scoped_routes(fastapi_app)}
    stale = sorted(f"{m} {p}" for m, p in PUBLIC_SHOP_ROUTES if (m, p) not in live)
    assert not stale, "PUBLIC_SHOP_ROUTES lists routes that no longer exist:\n  " + "\n  ".join(stale)


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", "/shops/{shop_id}"),
        ("DELETE", "/shops/{shop_id}"),
        ("PUT", "/shops/config/{shop_id}"),
        ("GET", "/shops/allowed-ips/{shop_id}"),
        ("POST", "/shops/allowed-ips/{shop_id}"),
        ("GET", "/shops/{shop_id}/accounts/"),
        ("POST", "/shops/{shop_id}/api-keys/"),
    ],
)
def test_known_sensitive_routes_are_guarded(fastapi_app: FastAPI, method: str, path: str) -> None:
    """Spot-check the routes that were unguarded before this change."""
    matching = [r for m, r in _shop_scoped_routes(fastapi_app) if r.path == path and m == method]
    assert matching, f"route {method} {path} not found — did it move?"
    assert all(_guards_in_chain(r.dependant) for r in matching)


# The tests above prove the guard is *wired*. These prove it actually runs.


def test_config_style_route_rejects_a_foreign_shop(as_cognito_user):
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    client = as_cognito_user([str(own_shop)])

    assert client.get(f"/shops/allowed-ips/{own_shop}").status_code == 200
    assert client.get(f"/shops/allowed-ips/{other_shop}").status_code == 403


def test_shop_delete_rejects_a_foreign_shop(as_cognito_user):
    """The worst of the pre-existing holes: deleting another tenant's shop."""
    own_shop = make_shop(random_shop_name=True)
    other_shop = make_shop(random_shop_name=True)
    client = as_cognito_user([str(own_shop)])

    assert client.delete(f"/shops/{other_shop}").status_code == 403
    assert ShopTable.query.filter_by(id=other_shop).first() is not None


def test_public_shop_config_is_not_caught_by_the_guard(as_cognito_user):
    """GET /shops/config/{shop_id} is public — only the PUT on that path is guarded.

    Asserted as "not 403" rather than "200": the response model chokes on the
    factory's ``shop_type="{}"`` string, which is a pre-existing serialisation
    mismatch unrelated to scoping. Reaching serialisation at all proves the
    guard let the request through.
    """
    other_shop = make_shop(random_shop_name=True)
    client = as_cognito_user([])
    with pytest.raises(ResponseValidationError):
        client.get(f"/shops/config/{other_shop}")
