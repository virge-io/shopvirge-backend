from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query

from server.api.endpoints.shops.common import shop_or_404
from server.api.error_handling import raise_status
from server.crud.crud_shop import shop_crud
from server.db.models import ShopTable
from server.schemas.shop import (
    ShopSchema,
    ShopUpdate,
)
from server.security import require_admin

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
    description="Permanently remove a shop from the platform. Requires Admins group membership.",
    dependencies=[Depends(require_admin)],
)
def delete(
    shop_id: UUID,
    force: bool = Query(False, description="Force delete shop and all related data via cascade."),
) -> None:
    """Delete a shop permanently (Admin only)."""
    # 1. First check if the shop exists
    shop_or_404(shop_id)

    # 2. If force is False, check if related data exists before attempting deletion
    if not force and shop_crud.has_related_data(shop_id):
        logger.warning(
            "Cannot delete shop because related data still exists",
            shop_id=str(shop_id),
        )
        raise_status(
            HTTPStatus.CONFLICT,
            detail="Cannot delete shop because related data still exists.",
        )

    # 3. Perform shop deletion
    shop_crud.delete(id=shop_id)
