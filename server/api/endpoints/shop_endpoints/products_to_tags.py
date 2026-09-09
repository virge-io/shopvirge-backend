from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_product import product_crud
from server.crud.crud_product_to_tag import product_to_tag_crud
from server.crud.crud_tag import tag_crud
from server.db import db
from server.db.models import ProductToTagTable
from server.schemas.product_to_tag import ProductToTagCreate, ProductToTagSchema, ProductToTagUpdate
from server.security import auth_required_any
from server.services.revisions import actor, ensure_baseline_product_revision, record_product_revision

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProductToTagSchema],
    operation_id="list_product_to_tags",
    summary="List product-tag associations",
    description="Returns all product-to-tag relationship records for a shop.",
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
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
    operation_id="get_product_to_tag_relation_id",
    summary="Get product-tag relation ID",
    description="Find the UUID of the association record between a specific product and tag. Returns 400 if the relation does not exist.",
    tags=[AgentTag.EXPOSED],
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
    operation_id="get_product_to_tag",
    summary="Get product-tag association",
    description="Retrieve a single product-to-tag association by its UUID.",
    tags=[AgentTag.EXPOSED],
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
    operation_id="create_product_to_tag",
    summary="Add tag to product",
    tags=[AgentTag.EXPOSED],
    description="Create an association between a product and a tag. Both must exist within the shop.",
)
def create(request: Request, data: ProductToTagCreate = Body(...), principal: Any = Depends(auth_required_any)) -> None:
    tag = tag_crud.get(data.tag_id)
    # Lock the product: tag links record a product revision and the shop UI
    # saves multiple links concurrently
    product = product_crud.get(data.product_id, for_update=True)

    if not tag or not product:
        raise_status(HTTPStatus.NOT_FOUND, "Tag or product not found")

    logger.info("Saving product_to_tag", data=data)
    ensure_baseline_product_revision(product)
    db.session.add(ProductToTagTable(**data.model_dump()))
    created_by, source = actor(principal, request)
    record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()
    return None


@router.put(
    "/{product_to_tag_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    operation_id="update_product_to_tag",
    summary="Update product-tag association",
    tags=[AgentTag.EXPOSED],
    description="Update an existing product-tag association record.",
)
def update(
    *,
    product_to_tag_id: UUID,
    item_in: ProductToTagUpdate,
    request: Request,
    principal: Any = Depends(auth_required_any),
) -> Any:
    product_to_tag = product_to_tag_crud.get(id=product_to_tag_id)
    logger.info("Updating product_to_tag", data=product_to_tag)
    if not product_to_tag:
        raise HTTPException(status_code=404, detail="Shop not found")

    product = product_crud.get(item_in.product_id, for_update=True)
    if product is not None:
        ensure_baseline_product_revision(product)
    product_to_tag = product_to_tag_crud.update(
        db_obj=product_to_tag,
        obj_in=item_in,
        commit=False,
    )
    if product is not None:
        created_by, source = actor(principal, request)
        record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()
    return product_to_tag


@router.delete(
    "/{product_to_tag_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    operation_id="delete_product_to_tag",
    summary="Remove tag from product",
    description="Delete the association between a product and a tag.",
    tags=[AgentTag.EXPOSED],
)
def delete(product_to_tag_id: UUID, request: Request, principal: Any = Depends(auth_required_any)) -> None:
    relation = product_to_tag_crud.get(product_to_tag_id)
    if not relation:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductToTag with id {product_to_tag_id} not found")
    product = product_crud.get(relation.product_id, for_update=True)
    if product is not None:
        ensure_baseline_product_revision(product)
    db.session.delete(relation)
    if product is not None:
        created_by, source = actor(principal, request)
        record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()
    return None
