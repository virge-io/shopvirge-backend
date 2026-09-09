from datetime import datetime
from http import HTTPStatus
from uuid import UUID

import structlog
from fastapi.param_functions import Depends
from starlette.responses import Response

from server.api.api_v1.router_fix import APIRouter
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.api.helpers import name_file, upload_file
from server.crud.crud_product import product_crud
from server.schemas.product import ProductImageDelete, ProductUpdate

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/")
def get_multi(response: Response, common: dict = Depends(common_parameters)):
    """List all product product images."""
    products, header_range = product_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return products


@router.get("/{id}")
def get_by_id(id: UUID):
    product = product_crud.get(id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {id} not found")
    return product


@router.put("/{id}", status_code=HTTPStatus.CREATED)
def put(*, id: UUID, item_in: ProductUpdate):
    item = product_crud.get(id=id)
    # todo: raise 404 o abort

    data = dict(item_in)

    product_update = False
    image_cols = ["image_1", "image_2", "image_3", "image_4", "image_5", "image_6"]
    for image_col in image_cols:
        if data.get(image_col) and isinstance(data[image_col], dict):
            name = name_file(image_col, item.name, getattr(item, image_col))
            upload_file(data[image_col]["src"], name) if item.name != "Test Product" else None
            product_update = True
            item_in.__setattr__(image_col, name)

    if product_update:
        item_in.__setattr__(
            "complete", True if data.get("image_1") and item.description_nl and item.description_en else False
        )
        item_in.__setattr__("modified_at", datetime.utcnow())

        item = product_crud.update(
            db_obj=item,
            obj_in=item_in,
        )

    return item


@router.put("/delete/{id}", status_code=HTTPStatus.CREATED)
def delete_image(*, id: UUID, col: ProductImageDelete):
    item = product_crud.get(id=id)

    if not item:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {id} not found")

    if not getattr(item, col.image):
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {id} has no image {col.image}")

    item_in = ProductUpdate(**item.__dict__.copy())

    setattr(item_in, col.image, None)
    item_in.modified_at = datetime.utcnow()

    return product_crud.update(
        db_obj=item,
        obj_in=item_in,
    )
