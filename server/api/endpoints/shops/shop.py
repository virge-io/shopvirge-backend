from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter

from server.api.endpoints.shops.common import shop_or_404
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable
from server.schemas.shop import (
    ShopSchema,
    ShopUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.put(
    "/{shop_id}",
    response_model=ShopSchema,
    status_code=HTTPStatus.CREATED,
    summary="Update shop",
    description="Update shop details such as name, description, and VAT rates.",
)
def update(*, shop_id: UUID, item_in: ShopUpdate) -> ShopTable:
    shop = shop_or_404(shop_id)
    logger.info("Updating shop", data=shop)
    return shop_crud.update(db_obj=shop, obj_in=item_in)


@router.delete(
    "/{shop_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete shop",
    description="Permanently remove a shop from the platform.",
)
def delete(shop_id: UUID) -> None:
    shop_crud.delete(id=shop_id)
