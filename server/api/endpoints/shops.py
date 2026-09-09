from datetime import datetime
from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from sqlalchemy import func
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import PageParams, page_params_for
from server.api.error_handling import raise_status
from server.api.route_helpers import get_or_404, list_page
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import ProductTable, ProductTranslationTable, ShopTable
from server.schemas.shop import (
    MyShopsResponse,
    ShopCacheStatus,
    ShopConfig,
    ShopConfigUpdate,
    ShopCreate,
    ShopIp,
    ShopLastCompletedOrder,
    ShopLastPendingOrder,
    ShopSchema,
    ShopUpdate,
    ShopWithPrices,
)
from server.security import CustomCognitoToken, auth_required, has_admin_group

# Four routers, one auth posture each. The guard is declared where the router is
# mounted in ``server/api/api.py`` — never per route — so a route added here
# cannot ship unguarded by omission:
#
#   router            collection ops (no shop in the path)        auth_required
#   public_router     storefront reads, polled before sign-in     none
#   shop_router       per-shop ops, path param ``{shop_id}``      shop_access_required
#   legacy_id_router  per-shop ops, path param ``{id}``           shop_access_required_by_id
#
# legacy_id_router exists only because those paths predate the ``{shop_id}``
# convention. FastAPI derives operation_id from the path template, so renaming
# the param changes the generated client symbol and argument key; that needs a
# coordinated shop-editor change. Splitting routers leaves the spec untouched.
router = APIRouter()
public_router = APIRouter()
shop_router = APIRouter()
legacy_id_router = APIRouter()
logger = structlog.get_logger(__name__)

shop_page_params = page_params_for(shop_crud)


def _shop_or_404(shop_id: UUID) -> ShopTable:
    return get_or_404(shop_crud.get(shop_id), f"Shop with id {shop_id} not found")


def _set_allowed_ips(shop: ShopTable, allowed_ips: List[str]) -> List[str]:
    """Persist a new order-submission allow-list; every other shop field is carried over unchanged."""
    shop_crud.update(
        db_obj=shop,
        obj_in=ShopUpdate(
            name=shop.name,
            description=shop.description,
            modified_at=datetime.utcnow(),
            allowed_ips=allowed_ips,
            vat_standard=shop.vat_standard,
            vat_lower_1=shop.vat_lower_1,
            vat_lower_2=shop.vat_lower_2,
            vat_lower_3=shop.vat_lower_3,
            vat_special=shop.vat_special,
            vat_zero=shop.vat_zero,
        ),
    )
    return allowed_ips


# --- router: collection operations -------------------------------------------


@router.get(
    "/",
    response_model=List[ShopSchema],
    summary="List shops",
    description="Returns all shops on the platform. Supports pagination, filtering, and sorting via common query parameters.",
)
def get_multi(response: Response, page: PageParams = Depends(shop_page_params)) -> List[ShopTable]:
    return list_page(shop_crud, page, response)


@router.get(
    "/my-shops",
    response_model=MyShopsResponse,
    tags=[AgentTag.EXPOSED],
    operation_id="list_my_shops",
    summary="List shops and capabilities for the current user",
    description=(
        "Returns the shops this user can manage, derived from their Cognito groups, "
        "plus capability flags the agent should use to tailor its welcome message and behaviour. "
        "Admins (group 'Admins') see all shops and have full write access. "
        "Tenant users see only the shop(s) whose ID matches one of their Cognito group names; "
        "their write access is also scoped to those shops. "
        "Always call this first — before saying anything to the user."
    ),
)
def get_my_shops(
    token: CustomCognitoToken = Depends(auth_required),
) -> MyShopsResponse:
    shops, _ = shop_crud.get_multi(skip=0, limit=1000, filter_parameters=[], sort_parameters=[])
    is_admin = has_admin_group(token.cognito_groups)
    if is_admin:
        accessible = shops
    else:
        accessible_ids = set(token.cognito_groups)
        accessible = [s for s in shops if str(s.id) in accessible_ids]
    return MyShopsResponse(shops=accessible, is_admin=is_admin, can_write=len(accessible) > 0)


@router.post(
    "/",
    response_model=ShopSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create shop",
    description="Create a new shop on the platform. Returns the created shop record.",
)
def create(data: ShopCreate = Body(...)) -> ShopTable:
    logger.info("Saving shop", data=data)
    return shop_crud.create(obj_in=data)


# --- public_router: storefront reads ----------------------------------------


@public_router.get(
    "/cache-status/{id}",
    response_model=ShopCacheStatus,
    summary="Get shop cache status",
    description="Returns the timestamp of the last data change visible in this shop. Useful for cache invalidation.",
)
def get_cache_status(id: UUID) -> ShopTable:
    return _shop_or_404(id)


@public_router.get(
    "/last-completed-order/{id}",
    response_model=ShopLastCompletedOrder,
    summary="Get timestamp of last completed order",
    description="Returns the timestamp of the most recently completed order for the shop. Used to detect new fulfilments.",
)
def get_last_completed_order(id: UUID) -> ShopTable:
    return _shop_or_404(id)


@public_router.get(
    "/last-pending-order/{id}",
    response_model=ShopLastPendingOrder,
    summary="Get timestamp of last pending order",
    description="Returns the timestamp of the most recently created pending order for the shop. Used by POS displays to detect new incoming orders.",
)
def get_last_pending_order(id: UUID) -> ShopTable:
    return _shop_or_404(id)


@public_router.get(
    "/{id}",
    response_model=ShopWithPrices,
    summary="Get shop",
    description="Retrieve a shop by its UUID, including all associated price records.",
)
def get_by_id(id: UUID) -> ShopTable:
    return _shop_or_404(id)


@public_router.get(
    "/config/{id}",
    response_model=ShopConfig,
    summary="Get shop configuration",
    description="Retrieve the shop's full configuration object, including feature toggles (e.g. stock tracking, checkout behaviour) and payment settings.",
)
def get_config(id: UUID) -> ShopTable:
    return _shop_or_404(id)


# --- shop_router: per-shop operations, ``{shop_id}`` -------------------------


@shop_router.put(
    "/{shop_id}",
    response_model=ShopSchema,
    status_code=HTTPStatus.CREATED,
    summary="Update shop",
    description="Update shop details such as name, description, and VAT rates.",
)
def update(*, shop_id: UUID, item_in: ShopUpdate) -> ShopTable:
    shop = _shop_or_404(shop_id)
    logger.info("Updating shop", data=shop)
    return shop_crud.update(db_obj=shop, obj_in=item_in)


@shop_router.delete(
    "/{shop_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete shop",
    description="Permanently remove a shop from the platform.",
)
def delete(shop_id: UUID) -> None:
    shop_crud.delete(id=shop_id)


# --- legacy_id_router: per-shop operations, ``{id}`` -------------------------


@legacy_id_router.put(
    "/config/{id}",
    response_model=ShopConfigUpdate,
    status_code=HTTPStatus.CREATED,
    summary="Update shop configuration",
    description="Update the shop's configuration. Partial updates are supported — only provided fields are changed.",
)
def update_config(id: UUID, item_in: ShopConfigUpdate) -> ShopTable:
    shop = _shop_or_404(id)
    logger.info("Updating shop", data=shop)

    if item_in.config.toggles.force_unique_product_names:
        duplicate = (
            db.session.query(ProductTranslationTable.main_name)
            .join(ProductTable, ProductTranslationTable.product_id == ProductTable.id)
            .filter(ProductTable.shop_id == id)
            .group_by(ProductTranslationTable.main_name)
            .having(func.count(ProductTranslationTable.main_name) > 1)
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot enable force_unique_product_names: duplicate product name '{duplicate[0]}' exists in this shop.",
            )

    return shop_crud.update(db_obj=shop, obj_in=item_in)


@legacy_id_router.get(
    "/allowed-ips/{id}",
    response_model=List[str],
    summary="List allowed IPs",
    description="Returns the list of IP addresses permitted to submit orders to this shop. An empty list means all IPs are allowed.",
)
def get_allowed_ips(id: UUID) -> List[str]:
    return list(_shop_or_404(id).allowed_ips or [])


@legacy_id_router.post(
    "/allowed-ips/{id}",
    response_model=List[str],
    summary="Add allowed IP",
    description="Add an IP address to the shop's order submission allowlist. Returns the updated list of allowed IPs.",
)
def add_new_ip(id: UUID, new_ip: ShopIp) -> List[str]:
    shop = _shop_or_404(id)
    allowed_ips = list(shop.allowed_ips or [])
    if new_ip.ip in allowed_ips:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {new_ip.ip} already exists")
    allowed_ips.append(new_ip.ip)
    return _set_allowed_ips(shop, allowed_ips)


@legacy_id_router.post(
    "/allowed-ips/{id}/remove",
    response_model=List[str],
    summary="Remove allowed IP",
    description="Remove an IP address from the shop's order submission allowlist. Returns the updated list.",
)
def remove_ip(id: UUID, old_ip: ShopIp) -> List[str]:
    shop = _shop_or_404(id)
    allowed_ips = list(shop.allowed_ips or [])
    if old_ip.ip not in allowed_ips:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {old_ip.ip} not on list")
    allowed_ips.remove(old_ip.ip)
    return _set_allowed_ips(shop, allowed_ips)
