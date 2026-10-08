from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter
from sqlalchemy.exc import IntegrityError

from server.api.endpoints.shops.common import shop_or_404
from server.api.error_handling import raise_status
from server.crud.base import NotFound
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
    try:
        shop_crud.delete(id=shop_id)
    except NotFound:
        raise_status(HTTPStatus.NOT_FOUND, f"Shop with id {shop_id} not found")
    except IntegrityError as e:
        logger.warning(
            "Cannot delete shop because related data still exists",
            shop_id=str(shop_id),
            error=str(e.orig if hasattr(e, "orig") and e.orig else e),
        )
        raise_status(
            HTTPStatus.CONFLICT,
            detail="Cannot delete shop because related data still exists.",
        )
