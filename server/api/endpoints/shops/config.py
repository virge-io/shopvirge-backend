from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from server.api.endpoints.shops.common import shop_or_404
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import ProductTable, ProductTranslationTable, ShopTable
from server.schemas.shop import (
    ShopConfigUpdate,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.put(
    "/config/{id}",
    response_model=ShopConfigUpdate,
    status_code=HTTPStatus.CREATED,
    summary="Update shop configuration",
    description="Update the shop's configuration. Partial updates are supported — only provided fields are changed.",
)
def update_config(id: UUID, item_in: ShopConfigUpdate) -> ShopTable:
    shop = shop_or_404(id)
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
