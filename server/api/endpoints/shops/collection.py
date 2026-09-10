from http import HTTPStatus
from typing import List

import structlog
from fastapi import APIRouter
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import PageParams, page_params_for
from server.api.route_helpers import list_page
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable
from server.schemas.shop import (
    MyShopsResponse,
    ShopCreate,
    ShopSchema,
)
from server.security import Principal, current_principal, has_admin_group

logger = structlog.get_logger(__name__)

router = APIRouter()

shop_page_params = page_params_for(shop_crud)


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
    principal: Principal = Depends(current_principal),
) -> MyShopsResponse:
    shops, _ = shop_crud.get_multi(skip=0, limit=1000, filter_parameters=[], sort_parameters=[])
    is_admin = has_admin_group(principal.groups)
    if is_admin:
        accessible = shops
    else:
        accessible_ids = set(principal.groups)
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
