from datetime import datetime, timezone
from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from fastapi.param_functions import Body, Depends
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_attribute import attribute_crud
from server.crud.crud_attribute_option import attribute_option_crud
from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable
from server.schemas.attribute_option import (
    AttributeOptionBase,
    AttributeOptionCreate,
    AttributeOptionSchema,
    AttributeOptionUpdate,
)

logger = structlog.get_logger(__name__)

deprecated_router = APIRouter()
router = APIRouter()


@deprecated_router.get(
    "/",
    response_model=List[AttributeOptionSchema],
    summary="List attribute options",
    description="Retrieve a paginated list of options (e.g., 'Small', 'Medium', 'Large') for a specific attribute within a shop.",
    deprecated=True,
)
def list_options(
    shop_id: UUID, attribute_id: UUID, response: Response, common: dict = Depends(common_parameters)
) -> List[AttributeOptionSchema]:
    """List options for an attribute within a shop."""
    # Ensure attribute belongs to shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    query = db.session.query(AttributeOptionTable).filter(AttributeOptionTable.attribute_id == attribute_id)
    results, content_range = attribute_option_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
        query_parameter=query,
    )
    response.headers["Content-Range"] = content_range
    return results


@deprecated_router.get(
    "/{option_id}",
    response_model=AttributeOptionSchema,
    summary="Get attribute option",
    description="Retrieve the details of a specific attribute option by its unique ID.",
    deprecated=True,
)
def get_option(shop_id: UUID, attribute_id: UUID, option_id: UUID) -> AttributeOptionSchema:
    """Get a single attribute option."""
    # Ensure attribute belongs to shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    option = attribute_option_crud.get(id=option_id)
    if not option or option.attribute_id != attribute_id:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this attribute")
    return option


@deprecated_router.post(
    "/",
    response_model=AttributeOptionSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create attribute option",
    description="Create a new option for a specific attribute. The value_key should be a language-agnostic identifier (e.g., 'XL').",
    deprecated=True,
)
def create_option(shop_id: UUID, attribute_id: UUID, data: dict = Body(...)) -> AttributeOptionSchema:
    """
    Create a new option for an attribute within a shop.

    Validates that the attribute exists and belongs to the given shop.
    The body must contain value_key; attribute_id from the path will be used.
    """
    # Ensure the attribute exists under the shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    value_key = data.get("value_key")
    if not value_key:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "value_key is required")

    payload = AttributeOptionBase(attribute_id=attribute_id, value_key=value_key)
    logger.info("Saving attribute option", attribute_id=str(attribute_id), value_key=payload.value_key)

    try:
        option = attribute_option_crud.create(obj_in=payload)
        return option
    except IntegrityError:
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {value_key} already exists for this attribute")


@deprecated_router.delete(
    "/{option_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete attribute option",
    description="Remove an attribute option. This will fail if the option is currently used by any product values.",
    deprecated=True,
)
def delete_option(
    shop_id: UUID,
    attribute_id: UUID,
    option_id: UUID,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
) -> None:
    """Delete an attribute option."""
    # Ensure attribute belongs to shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    option = attribute_option_crud.get(id=option_id)
    if not option or option.attribute_id != attribute_id:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this attribute")

    if force:
        try:
            attribute_option_crud.delete(id=str(option_id))
        except IntegrityError:
            raise_status(
                HTTPStatus.CONFLICT,
                detail={"message": "Attribute option is in use and cannot be deleted"},
            )
        return None

    option.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return None


@router.get(
    "/",
    response_model=List[AttributeOptionSchema],
    summary="List attribute options for a shop",
    description="Retrieve a paginated list of all attribute options (e.g., 'Small', 'XL') across all attributes within a shop.",
)
def list_options_for_shop(
    shop_id: UUID, response: Response, common: dict = Depends(common_parameters)
) -> List[AttributeOptionSchema]:
    """List all options for all attributes within a shop."""
    query = db.session.query(AttributeOptionTable).join(AttributeTable).filter(AttributeTable.shop_id == shop_id)
    results, content_range = attribute_option_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
        query_parameter=query,
    )
    response.headers["Content-Range"] = content_range
    return results


@router.post(
    "/",
    response_model=AttributeOptionSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create attribute option",
    description="Create a new option for a specific attribute within a shop. The attribute_id must be provided in the request body.",
)
def create_option_v2(shop_id: UUID, data: AttributeOptionCreate = Body(...)) -> AttributeOptionSchema:
    """
    Create a new option for an attribute within a shop.

    Validates that the attribute exists and belongs to the given shop.
    """
    # Ensure the attribute exists under the shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=data.attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {data.attribute_id} not found for this shop")

    logger.info("Saving attribute option", attribute_id=str(data.attribute_id), value_key=data.value_key)

    try:
        option = attribute_option_crud.create(obj_in=data)
        return option
    except IntegrityError:
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {data.value_key} already exists for this attribute")


@router.get(
    "/{option_id}",
    response_model=AttributeOptionSchema,
    summary="Get attribute option",
    description="Retrieve the details of a specific attribute option by its unique ID, ensuring it belongs to the shop.",
)
def get_option_v2(shop_id: UUID, option_id: UUID) -> AttributeOptionSchema:
    """Get a single attribute option by ID."""
    option = (
        db.session.query(AttributeOptionTable)
        .join(AttributeTable)
        .filter(AttributeOptionTable.id == option_id, AttributeTable.shop_id == shop_id)
        .first()
    )
    if not option:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this shop")
    return option


@router.put(
    "/{option_id}",
    response_model=AttributeOptionSchema,
    summary="Update attribute option",
    description="Update the details of an existing attribute option, ensuring it belongs to the shop.",
)
def update_option_v2(shop_id: UUID, option_id: UUID, data: AttributeOptionUpdate = Body(...)) -> AttributeOptionSchema:
    """Update an attribute option."""
    option = (
        db.session.query(AttributeOptionTable)
        .join(AttributeTable)
        .filter(AttributeOptionTable.id == option_id, AttributeTable.shop_id == shop_id)
        .first()
    )
    if not option:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this shop")

    try:
        return attribute_option_crud.update(db_obj=option, obj_in=data)
    except IntegrityError:
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {data.value_key} already exists for this attribute")


@router.delete(
    "/{option_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete attribute option",
    description="Remove an attribute option, ensuring it belongs to the shop.",
)
def delete_option_v2(
    shop_id: UUID,
    option_id: UUID,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
) -> None:
    """Delete an attribute option."""
    option = (
        db.session.query(AttributeOptionTable)
        .join(AttributeTable)
        .filter(AttributeOptionTable.id == option_id, AttributeTable.shop_id == shop_id)
        .execution_options(include_deleted=force)
        .first()
    )
    if not option:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this shop")

    if force:
        try:
            attribute_option_crud.delete(id=str(option_id))
        except IntegrityError:
            raise_status(
                HTTPStatus.CONFLICT,
                detail={"message": "Attribute option is in use and cannot be deleted"},
            )
        return None

    option.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return None
