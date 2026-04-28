import json
from http import HTTPStatus
from typing import Any, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api import deps
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.api.helpers import load
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable, UserTable
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
from server.security import ADMIN_GROUP, CustomCognitoToken, auth_required

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get(
    "/",
    response_model=List[ShopSchema],
    summary="List shops",
    description="Returns all shops on the platform. Supports pagination, filtering, and sorting via common query parameters.",
)
def get_multi(
    response: Response,
    common: dict = Depends(common_parameters),
    current_user: UserTable = Depends(auth_required),
) -> List[ShopSchema]:
    shops, header_range = shop_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return shops


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
    is_admin = ADMIN_GROUP in token.cognito_groups
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
def create(data: ShopCreate = Body(...), current_user: UserTable = Depends(auth_required)) -> ShopSchema:
    logger.info("Saving shop", data=data)
    shop = shop_crud.create(obj_in=data)
    return shop


@router.get(
    "/cache-status/{id}",
    response_model=ShopCacheStatus,
    summary="Get shop cache status",
    description="Returns the timestamp of the last data change visible in this shop. Useful for cache invalidation.",
)
def get_cache_status(id: UUID) -> ShopCacheStatus:
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")
    return shop


@router.get(
    "/last-completed-order/{id}",
    response_model=ShopLastCompletedOrder,
    summary="Get timestamp of last completed order",
    description="Returns the timestamp of the most recently completed order for the shop. Used to detect new fulfilments.",
)
def get_last_completed_order(id: UUID) -> ShopLastCompletedOrder:
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")
    return shop


@router.get(
    "/last-pending-order/{id}",
    response_model=ShopLastPendingOrder,
    summary="Get timestamp of last pending order",
    description="Returns the timestamp of the most recently created pending order for the shop. Used by POS displays to detect new incoming orders.",
)
def get_last_pending_order(id: UUID) -> ShopLastPendingOrder:
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")
    return shop


@router.get(
    "/{id}",
    response_model=ShopWithPrices,
    summary="Get shop",
    description="Retrieve a shop by its UUID, including all associated price records.",
)
def get_by_id(id: UUID):
    item = load(ShopTable, id)
    return item


@router.put(
    "/{shop_id}",
    response_model=ShopSchema,
    status_code=HTTPStatus.CREATED,
    summary="Update shop",
    description="Update shop details such as name, description, and VAT rates.",
)
def update(*, shop_id: UUID, item_in: ShopUpdate, current_user: UserTable = Depends(auth_required)) -> None:
    shop = shop_crud.get(id=shop_id)
    logger.info("Updating shop", data=shop)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop = shop_crud.update(
        db_obj=shop,
        obj_in=item_in,
    )
    return shop


@router.delete(
    "/{shop_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete shop",
    description="Permanently remove a shop from the platform.",
)
def delete(shop_id: UUID, current_user: UserTable = Depends(auth_required)) -> None:
    return shop_crud.delete(id=shop_id)


@router.get(
    "/config/{id}",
    response_model=ShopConfig,
    summary="Get shop configuration",
    description="Retrieve the shop's full configuration object, including feature toggles (e.g. stock tracking, checkout behaviour) and payment settings.",
)
def get_config(
    id: UUID,
) -> ShopConfig:
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")

    return shop


@router.put(
    "/config/{id}",
    response_model=ShopConfigUpdate,
    status_code=HTTPStatus.CREATED,
    summary="Update shop configuration",
    description="Update the shop's configuration. Partial updates are supported — only provided fields are changed.",
)
def update_config(
    id: UUID,
    item_in: ShopConfigUpdate,
    current_user: UserTable = Depends(auth_required),
) -> ShopConfig:
    shop = shop_crud.get(id=id)
    logger.info("Updating shop", data=shop)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop = shop_crud.update(
        db_obj=shop,
        obj_in=item_in,
    )
    return shop


@router.get(
    "/allowed-ips/{id}",
    response_model=List[str],
    summary="List allowed IPs",
    description="Returns the list of IP addresses permitted to submit orders to this shop. An empty list means all IPs are allowed.",
)
def get_allowed_ips(
    id: UUID,
    current_user: UserTable = Depends(auth_required),
) -> List[str]:
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")

    if shop.allowed_ips:
        return shop.allowed_ips
    else:
        return []


@router.post(
    "/allowed-ips/{id}",
    response_model=List[str],
    summary="Add allowed IP",
    description="Add an IP address to the shop's order submission allowlist. Returns the updated list of allowed IPs.",
)
def add_new_ip(id: UUID, new_ip: ShopIp, current_user: UserTable = Depends(auth_required)):
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")

    updated_shop = ShopUpdate(
        name=shop.name,
        description=shop.description,
        allowed_ips=shop.allowed_ips,
        vat_standard=shop.vat_standard,
        vat_lower_1=shop.vat_lower_1,
        vat_lower_2=shop.vat_lower_2,
        vat_lower_3=shop.vat_lower_3,
        vat_special=shop.vat_special,
        vat_zero=shop.vat_zero,
    )

    if shop.allowed_ips and new_ip.ip not in shop.allowed_ips:
        updated_shop.allowed_ips.append(new_ip.ip)
    elif shop.allowed_ips and new_ip.ip in shop.allowed_ips:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {new_ip.ip} already exists")
    else:
        updated_shop.allowed_ips = [new_ip.ip]

    shop_crud.update(db_obj=shop, obj_in=updated_shop)

    return updated_shop.allowed_ips


@router.post(
    "/allowed-ips/{id}/remove",
    response_model=List[str],
    summary="Remove allowed IP",
    description="Remove an IP address from the shop's order submission allowlist. Returns the updated list.",
)
def remove_ip(id: UUID, old_ip: ShopIp, current_user: UserTable = Depends(auth_required)):
    shop = shop_crud.get(id)
    if not shop:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {id} not found")

    updated_shop = ShopUpdate(
        name=shop.name,
        description=shop.description,
        allowed_ips=shop.allowed_ips,
        vat_standard=shop.vat_standard,
        vat_lower_1=shop.vat_lower_1,
        vat_lower_2=shop.vat_lower_2,
        vat_lower_3=shop.vat_lower_3,
        vat_special=shop.vat_special,
        vat_zero=shop.vat_zero,
    )

    if shop.allowed_ips and old_ip.ip in shop.allowed_ips:
        updated_shop.allowed_ips.remove(old_ip.ip)
    else:
        raise_status(HTTPStatus.BAD_REQUEST, f"IP {old_ip.ip} not on list")

    shop_crud.update(db_obj=shop, obj_in=updated_shop)

    return updated_shop.allowed_ips
