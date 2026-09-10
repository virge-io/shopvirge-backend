from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from fastapi.param_functions import Body, Depends
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.endpoints.attributes.options import _delete_option
from server.api.error_handling import raise_status
from server.crud.crud_attribute import attribute_crud
from server.crud.crud_attribute_option import attribute_option_crud
from server.db import db
from server.db.models import AttributeOptionTable
from server.schemas.attribute_option import (
    AttributeOptionSchema,
)
from server.security import Principal, current_principal
from server.services.revisions import ensure_baseline_attribute_revision, record_attribute_revision

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
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


@router.get(
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


@router.post(
    "/",
    response_model=AttributeOptionSchema,
    status_code=HTTPStatus.CREATED,
    summary="Create attribute option",
    description="Create a new option for a specific attribute. The value_key should be a language-agnostic identifier (e.g., 'XL').",
    deprecated=True,
)
def create_option(
    shop_id: UUID,
    attribute_id: UUID,
    data: dict = Body(...),
    principal: Principal = Depends(current_principal),
) -> AttributeOptionSchema:
    """Create a new option for an attribute within a shop.

    Validates that the attribute exists and belongs to the given shop.
    The body must contain value_key; attribute_id from the path will be used.
    """
    # Ensure the attribute exists under the shop; lock it so concurrent option
    # writes serialize on attribute revision numbering
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id, for_update=True)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    value_key = data.get("value_key")
    if not value_key:
        raise_status(HTTPStatus.UNPROCESSABLE_ENTITY, "value_key is required")

    logger.info("Saving attribute option", attribute_id=str(attribute_id), value_key=value_key)

    ensure_baseline_attribute_revision(attribute)
    option = AttributeOptionTable(attribute_id=attribute_id, value_key=value_key)
    db.session.add(option)
    try:
        record_attribute_revision(attribute, action="update", created_by=principal.label, source=principal.via)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {value_key} already exists for this attribute")
    db.session.refresh(option)
    return option


@router.delete(
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
    principal: Principal = Depends(current_principal),
) -> None:
    """Delete an attribute option."""
    # Ensure attribute belongs to shop; lock for revision numbering
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=attribute_id, for_update=True)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {attribute_id} not found for this shop")

    option = attribute_option_crud.get(id=option_id)
    if not option or option.attribute_id != attribute_id:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this attribute")

    return _delete_option(attribute, option, force, principal)
