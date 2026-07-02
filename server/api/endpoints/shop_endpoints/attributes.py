from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, List
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.param_functions import Body, Depends
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.base import NotFound
from server.crud.crud_attribute import attribute_crud
from server.db import db
from server.db.models import ApiKeyTable, AttributeOptionTable
from server.schemas.attribute import (
    AttributeBase,
    AttributeCreate,
    AttributeSchema,
    AttributeTranslationBase,
    AttributeUpdate,
    AttributeWithOptionsSchema,
)
from server.security import auth_required_any

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/{attribute_id}/with-options",
    response_model=AttributeWithOptionsSchema,
    summary="Get attribute by ID with options",
    description="Retrieve a specific attribute by its unique ID, including all of its defined options.",
)
def get_by_id_with_options_direct(attribute_id: UUID, shop_id: UUID) -> AttributeWithOptionsSchema:
    """Get a single attribute for a shop including its options."""
    attribute = attribute_crud.get_id_by_shop_id(shop_id, attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")

    # Fetch all options for this attribute
    options = db.session.query(AttributeOptionTable).filter(AttributeOptionTable.attribute_id == attribute_id).all()
    attribute.options = options
    return attribute


@router.get(
    "/with-options",
    response_model=List[AttributeWithOptionsSchema],
    summary="List shop attributes with options",
    description="Retrieve a paginated list of all attributes belonging to a specific shop, including their associated options (e.g., sizes or colors).",
)
def get_with_options(
    shop_id: UUID, response: Response, common: dict = Depends(common_parameters)
) -> List[AttributeWithOptionsSchema]:
    """List attributes for a shop including their options."""
    # Base: all attributes for this shop (paginated)
    items, header_range = attribute_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range

    if not items:
        return []

    attr_ids = [a.id for a in items]
    # Fetch all options for these attributes in one query
    options = db.session.query(AttributeOptionTable).filter(AttributeOptionTable.attribute_id.in_(attr_ids)).all()
    options_by_attr: dict[UUID, list[AttributeOptionTable]] = {}
    for opt in options:
        options_by_attr.setdefault(opt.attribute_id, []).append(opt)

    # Attach options
    result: List[AttributeWithOptionsSchema] = []
    for attr in items:
        attr.options = options_by_attr.get(attr.id, [])
        result.append(attr)
    return result


@router.get(
    "/",
    response_model=List[AttributeSchema],
    summary="List shop attributes",
    description="Retrieve a paginated list of all attributes defined for a specific shop. This list does not include options.",
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_attributes",
)
def get_multi(shop_id: UUID, response: Response, common: dict = Depends(common_parameters)) -> List[AttributeSchema]:
    """List attributes for a shop."""
    items, header_range = attribute_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return items


@router.get(
    "/id/{attribute_id}/with-options",
    response_model=AttributeWithOptionsSchema,
    summary="Get attribute by ID with options",
    description="Retrieve a specific attribute by its unique ID, including all of its defined options.",
)
def get_by_id_with_options(attribute_id: UUID, shop_id: UUID) -> AttributeWithOptionsSchema:
    """Get a single attribute for a shop including its options."""
    attribute = attribute_crud.get_id_by_shop_id(shop_id, attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")

    # Fetch all options for this attribute
    options = db.session.query(AttributeOptionTable).filter(AttributeOptionTable.attribute_id == attribute_id).all()
    attribute.options = options
    return attribute


@router.get(
    "/id/{attribute_id}",
    response_model=AttributeSchema,
    summary="Get attribute by ID",
    description="Retrieve the details of a specific attribute using its unique ID.",
    tags=[AgentTag.EXPOSED],
    operation_id="get_attribute",
)
def get_by_id(attribute_id: UUID, shop_id: UUID) -> AttributeSchema:
    """Get a single attribute for a shop by its ID."""
    attribute = attribute_crud.get_id_by_shop_id(shop_id, attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")
    return attribute


@router.get(
    "/name/{name}",
    response_model=AttributeSchema,
    summary="Get attribute by name",
    description="Retrieve the details of a specific attribute using its machine-friendly name (e.g., 'color').",
)
def get_by_name(name: str, shop_id: UUID) -> AttributeSchema:
    """Get a single attribute for a shop by its name."""
    attribute = attribute_crud.get_by_name(name=name, shop_id=shop_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with name {name} not found")
    return attribute


@router.post(
    "/",
    response_model=AttributeSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create attribute",
    description="Create a new attribute for a shop. This also initializes a translation record with the provided name.",
    tags=[AgentTag.EXPOSED],
    operation_id="create_attribute",
)
def create(shop_id: UUID, data: AttributeCreate = Body(...)) -> AttributeSchema:
    """
    Create a new attribute for the given shop.

    This will also create the translation row and currently only requires main_name in translation.
    """
    logger.info("Saving attribute", data=data)

    if data.translation is None or data.translation.main_name is None:
        data.translation = AttributeTranslationBase(main_name=data.name)

    try:
        attr = attribute_crud.create_by_shop_id(shop_id=shop_id, obj_in=data)
    except IntegrityError:
        raise_status(HTTPStatus.CONFLICT, f"Attribute with name {data.name} already exists for this shop")
    return attr


@router.put(
    "/{attribute_id}",
    response_model=AttributeSchema,
    summary="Update attribute",
    description="Update the details of an existing attribute, such as its name or unit.",
    tags=[AgentTag.EXPOSED],
    operation_id="update_attribute",
)
def update(attribute_id: UUID, shop_id: UUID, data: AttributeUpdate = Body(...)) -> AttributeSchema:
    """Update an attribute for a shop."""
    attribute = attribute_crud.get_id_by_shop_id(shop_id, attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")

    try:
        return attribute_crud.update(db_obj=attribute, obj_in=data)
    except IntegrityError:
        raise_status(HTTPStatus.CONFLICT, f"Attribute with name {data.name} already exists for this shop")


@router.delete(
    "/{attribute_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete attribute (moves to trash)",
    description=(
        "Moves an attribute to the trash: it disappears from listings but existing product values keep "
        "their data, so restoring the attribute brings everything back. This action is reversible. "
        "Only `force=true` permanently purges the attribute (fails with 409 while products still use it); "
        "that is irreversible and requires user (Cognito) credentials — API keys get 403."
    ),
    tags=[AgentTag.EXPOSED],
    operation_id="delete_attribute",
)
def delete(
    attribute_id: UUID,
    shop_id: UUID,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
    principal: Any = Depends(auth_required_any),
) -> None:
    """Delete an attribute for a shop."""
    attribute = attribute_crud.get_id_by_shop_id(shop_id, attribute_id, for_update=True, include_deleted=force)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")

    if force:
        if isinstance(principal, ApiKeyTable):
            raise HTTPException(
                status_code=403,
                detail="Purging an attribute is irreversible and requires user credentials; API keys may only trash.",
            )
        try:
            return attribute_crud.delete_by_shop_id(shop_id=shop_id, id=attribute_id, include_deleted=True)
        except NotFound:
            raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found")
        except IntegrityError:
            raise_status(
                HTTPStatus.CONFLICT,
                detail={"message": "Attribute is in use and cannot be deleted"},
            )

    attribute.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return None
