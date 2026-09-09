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
"""Compose every endpoint package into ``api_router``.

Routes are grouped into *tiers* by auth posture. A tier is an ``APIRouter``
that carries its guard once; each domain plugs its routers into the tier that
matches their posture, so a guard is never written per include and never per
route. Prefixes and tags stay on the include, exactly as before the packages.

    public          none                          storefront, checkout, system
    authenticated   auth_required                 collection management
    admin           admin_required                cross-shop admin views
    shop            shop_access_required          per-shop, Cognito only
    shop_any        auth_required_any_for_shop    per-shop, API key or Cognito

Two routers are included outside the tiers with their guard spelled out:
``shops.legacy_id_router`` (its paths spell the shop id ``{id}``) and
``orders.per_shop_router`` (orders mount at ``/orders``, not under the shop).
They go away with the path-param rename and the orders merge respectively.

Registration order matters: FastAPI matches routes in the order they were
added, so ``authenticated`` (which holds ``GET /shops/my-shops``) must be
registered before ``public`` (which holds ``GET /shops/{id}``).
``test_router_posture.py`` asserts that no route is shadowed by an earlier one.
"""

from fastapi import APIRouter, Depends

from server.api.endpoints import (
    accounts,
    attributes,
    categories,
    checkout,
    content,
    images,
    orders,
    products,
    revisions,
    shops,
    system,
    tags,
)
from server.security import (
    admin_required,
    auth_required,
    auth_required_any_for_shop,
    shop_access_required,
    shop_access_required_by_id,
)
from server.settings import mail_settings

public = APIRouter()
authenticated = APIRouter(dependencies=[Depends(auth_required)])
admin = APIRouter(dependencies=[Depends(admin_required)])
shop = APIRouter(dependencies=[Depends(shop_access_required)])
shop_any = APIRouter(dependencies=[Depends(auth_required_any_for_shop)])

# --- authenticated: Cognito token, any user ---------------------------------
authenticated.include_router(system.forms_router, prefix="/forms", tags=["forms"])
authenticated.include_router(shops.collection_router, prefix="/shops", tags=["shops"])
authenticated.include_router(orders.management_router, prefix="/orders", tags=["orders"])
authenticated.include_router(content.early_access_router, prefix="/early-access", tags=["early-access"])
authenticated.include_router(content.faq_router, prefix="/faq", tags=["faq"])

# --- admin: Cognito token in the admins group -------------------------------
admin.include_router(accounts.admin_router, prefix="/admin/accounts", tags=["admin", "accounts"])

# --- shop: Cognito token with access to {shop_id} ---------------------------
shop.include_router(shops.shop_router, prefix="/shops", tags=["shops"])
shop.include_router(categories.images_router, prefix="/shops/{shop_id}/categories-images", tags=["shops", "categories"])
shop.include_router(images.shop_router, prefix="/shops/{shop_id}/images", tags=["shops", "images"])
# Cognito-only: a key must not be able to mint another key, and a user must
# not be able to mint one for a shop they have no access to.
shop.include_router(accounts.api_keys_router, prefix="/shops/{shop_id}/api-keys", tags=["shops", "api-keys"])
shop.include_router(
    attributes.deprecated_options_router,
    prefix="/shops/{shop_id}/attributes/{attribute_id}/options",
    tags=["shops", "attributes"],
)
shop.include_router(accounts.shop_router, prefix="/shops/{shop_id}/accounts", tags=["shops", "accounts"])

# --- shop_any: per-shop API key or Cognito token — the MCP-exposed surface --
shop_any.include_router(categories.router, prefix="/shops/{shop_id}/categories", tags=["categories"])
shop_any.include_router(products.router, prefix="/shops/{shop_id}/products", tags=["shops", "products"])
shop_any.include_router(
    products.product_tags_router, prefix="/shops/{shop_id}/products-to-tags", tags=["shops", "products"]
)
shop_any.include_router(revisions.router, prefix="/shops/{shop_id}", tags=["shops", "revisions"])
shop_any.include_router(tags.router, prefix="/shops/{shop_id}/tags", tags=["shops", "products"])
shop_any.include_router(attributes.router, prefix="/shops/{shop_id}/attributes", tags=["shops", "attributes"])
shop_any.include_router(
    attributes.options_router, prefix="/shops/{shop_id}/attribute-options", tags=["shops", "attributes"]
)
shop_any.include_router(
    products.attribute_values_router,
    prefix="/shops/{shop_id}/product-attribute-values",
    tags=["shops", "products", "attributes"],
)

# --- public: no auth --------------------------------------------------------
public.include_router(system.oauth_discovery_router, tags=["oauth"])
public.include_router(system.health_router, prefix="/health", tags=["system"])
public.include_router(images.public_router, prefix="/images", tags=["images"])
# licenses guards its write routes per route; it moves to `authenticated` once split.
public.include_router(content.licenses_router, prefix="/licenses", tags=["licenses"])
public.include_router(content.downloads_router, prefix="/downloads", tags=["downloads"])
public.include_router(shops.public_router, prefix="/shops", tags=["shops"])
public.include_router(products.prices_router, prefix="/shops/{shop_id}/prices", tags=["shops"])
public.include_router(orders.public_router, prefix="/orders", tags=["orders"])
public.include_router(checkout.shipping_router, prefix="/shipping", tags=["shipping"])
public.include_router(categories.public_router, prefix="/shops/{shop_id}/categories", tags=["categories"])
public.include_router(products.public_router, prefix="/shops/{shop_id}/products", tags=["shops", "products"])
public.include_router(checkout.stripe_router, prefix="/shops/{shop_id}/stripe", tags=["stripe"])
public.include_router(content.info_request_router, prefix="/info-request", tags=["info-request"])
public.include_router(system.sentry_test_router, prefix="/sentry", tags=["sentry"])
public.include_router(system.test_forms_router, prefix="/test-forms", tags=["test-forms"])
public.include_router(content.faq_public_router, prefix="/faq", tags=["faq"])
if mail_settings.MAIL_TEST_ENDPOINT_ENABLED:
    public.include_router(system.mail_test_router, prefix="/mail-test", tags=["mail-test"])

api_router = APIRouter()
api_router.include_router(authenticated)
api_router.include_router(admin)
api_router.include_router(shop)
api_router.include_router(shop_any)
api_router.include_router(
    shops.legacy_id_router,
    prefix="/shops",
    tags=["shops"],
    dependencies=[Depends(shop_access_required_by_id)],
)
api_router.include_router(
    orders.per_shop_router,
    prefix="/orders",
    tags=["orders"],
    dependencies=[Depends(auth_required_any_for_shop)],
)
api_router.include_router(public)
