from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_product import product_crud
from server.crud.crud_product_to_tag import product_to_tag_crud
from server.crud.crud_tag import tag_crud
from server.schemas.product_to_tag import ProductToTagCreate, ProductToTagSchema, ProductToTagUpdate

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProductToTagSchema],
    summary="List product-tag associations",
    description="Returns all product-to-tag relationship records for a shop.",
)
def get_multi(response: Response, common: dict = Depends(common_parameters)) -> List[ProductToTagSchema]:
    query_result, content_range = product_to_tag_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = content_range
    return query_result


@router.get(
    "/get_relation_id",
    summary="Get product-tag relation ID",
    description="Find the UUID of the association record between a specific product and tag. Returns 400 if the relation does not exist.",
)
def get_relation_id(tag_id: UUID, product_id: UUID) -> None:
    tag = tag_crud.get(tag_id)
    product = product_crud.get(product_id)

    if not tag or not product:
        raise_status(HTTPStatus.NOT_FOUND, "Tag or product not found")

    relation = product_to_tag_crud.get_relation_by_product_tag(product_id=product.id, tag_id=tag.id)

    if not relation:
        raise_status(HTTPStatus.BAD_REQUEST, "Relation doesn't exist")

    return relation.id


@router.get(
    "/{id}",
    response_model=ProductToTagSchema,
    summary="Get product-tag association",
    description="Retrieve a single product-to-tag association by its UUID.",
)
def get_by_id(id: UUID) -> ProductToTagSchema:
    product_to_tag = product_to_tag_crud.get(id)
    if not product_to_tag:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductToTag with id {id} not found")
    return product_to_tag


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Add tag to product",
    description="Create an association between a product and a tag. Both must exist within the shop.",
)
def create(data: ProductToTagCreate = Body(...)) -> None:
    tag = tag_crud.get(data.tag_id)
    product = product_crud.get(data.product_id)

    if not tag or not product:
        raise_status(HTTPStatus.NOT_FOUND, "Tag or product not found")

    logger.info("Saving product_to_tag", data=data)
    return product_to_tag_crud.create(obj_in=data)


@router.put(
    "/{product_to_tag_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Update product-tag association",
    description="Update an existing product-tag association record.",
)
def update(*, product_to_tag_id: UUID, item_in: ProductToTagUpdate) -> Any:
    product_to_tag = product_to_tag_crud.get(id=product_to_tag_id)
    logger.info("Updating product_to_tag", data=product_to_tag)
    if not product_to_tag:
        raise HTTPException(status_code=404, detail="Shop not found")

    product_to_tag = product_to_tag_crud.update(
        db_obj=product_to_tag,
        obj_in=item_in,
    )
    return product_to_tag


@router.delete(
    "/{product_to_tag_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Remove tag from product",
    description="Delete the association between a product and a tag.",
)
def delete(product_to_tag_id: UUID) -> None:
    return product_to_tag_crud.delete(id=product_to_tag_id)
