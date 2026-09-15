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
that carries its guard — and, for the per-shop tiers, the ``/shops/{shop_id}``
prefix — exactly once. Each package's ``router.py`` composes that package's
modules under their own path segment with their tags, and is included here
once per tier it takes part in. Nothing below spells a full path or a guard
per include.

    public          none                          storefront, checkout, system
    shop_public     none, /shops/{shop_id}        per-shop storefront reads
    authenticated   auth_required                 collection management
    admin           admin_required                cross-shop admin views
    shop            shop_access_required          per-shop, Cognito only
    shop_any        auth_required_any_for_shop    per-shop, API key or Cognito

Three routers are included outside the tiers with their guard spelled out,
because their own path is the shop segment rather than something under it:
``shops.shop_router`` (``/shops/{shop_id}``), ``shops.legacy_id_router``
(``/shops/…/{id}``) and ``orders.per_shop_router`` (``/orders/shop/{shop_id}``).
The path-param rename and the orders merge remove them.

Registration order matters: FastAPI matches routes in the order they were
added, so ``authenticated`` (``GET /shops/my-shops``) must precede ``public``
(``GET /shops/{id}``). ``test_router_posture.py`` asserts no route is shadowed.
"""

from fastapi import APIRouter, Depends

from server.api.endpoints.accounts import router as accounts
from server.api.endpoints.attributes import router as attributes
from server.api.endpoints.categories import router as categories
from server.api.endpoints.checkout import router as checkout
from server.api.endpoints.content import router as content
from server.api.endpoints.images import router as images
from server.api.endpoints.orders import router as orders
from server.api.endpoints.products import router as products
from server.api.endpoints.revisions import router as revisions
from server.api.endpoints.shops import router as shops
from server.api.endpoints.system import router as system
from server.api.endpoints.tags import router as tags
from server.security import (
    admin_required,
    auth_required,
    auth_required_any_for_shop,
    shop_access_required,
    shop_access_required_by_id,
)

SHOP = "/shops/{shop_id}"

public = APIRouter()
shop_public = APIRouter(prefix=SHOP)
authenticated = APIRouter(dependencies=[Depends(auth_required)])
admin = APIRouter(dependencies=[Depends(admin_required)])
shop = APIRouter(prefix=SHOP, dependencies=[Depends(shop_access_required)])
shop_any = APIRouter(prefix=SHOP, dependencies=[Depends(auth_required_any_for_shop)])

authenticated.include_router(system.router)
authenticated.include_router(shops.router)
authenticated.include_router(orders.router)
authenticated.include_router(content.router)

admin.include_router(accounts.admin_router)

shop.include_router(categories.shop_router)
shop.include_router(images.shop_router)
shop.include_router(accounts.shop_router)
shop.include_router(attributes.shop_router)

shop_any.include_router(categories.router)
shop_any.include_router(products.router)
shop_any.include_router(revisions.router)
shop_any.include_router(tags.router)
shop_any.include_router(attributes.router)

shop_public.include_router(products.public_router)
shop_public.include_router(categories.public_router)
shop_public.include_router(checkout.shop_public_router)

public.include_router(system.public_router)
public.include_router(images.public_router)
public.include_router(content.public_router)
public.include_router(shops.public_router)
public.include_router(orders.public_router)
public.include_router(checkout.public_router)

api_router = APIRouter()
api_router.include_router(authenticated)
api_router.include_router(admin)
api_router.include_router(shop)
api_router.include_router(shop_any)
api_router.include_router(
    shops.shop_router, prefix="/shops", tags=["shops"], dependencies=[Depends(shop_access_required)]
)
api_router.include_router(
    shops.legacy_id_router, prefix="/shops", tags=["shops"], dependencies=[Depends(shop_access_required_by_id)]
)
api_router.include_router(
    orders.per_shop_router, prefix="/orders", tags=["orders"], dependencies=[Depends(auth_required_any_for_shop)]
)
api_router.include_router(shop_public)
api_router.include_router(public)
