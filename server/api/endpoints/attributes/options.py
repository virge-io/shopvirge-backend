from datetime import datetime, timezone
from http import HTTPStatus
from typing import List
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from fastapi.param_functions import Body, Depends
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_attribute import attribute_crud
from server.crud.crud_attribute_option import attribute_option_crud
from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable
from server.schemas.attribute_option import (
    AttributeOptionCreate,
    AttributeOptionSchema,
    AttributeOptionUpdate,
)
from server.security import Principal, current_principal
from server.services.revisions import ensure_baseline_attribute_revision, record_attribute_revision

logger = structlog.get_logger(__name__)

router = APIRouter()


def _delete_option(attribute: AttributeTable, option: AttributeOptionTable, force: bool, principal: Principal) -> None:
    """Shared delete flow: soft delete by default, hard purge with force; both record an attribute revision."""
    ensure_baseline_attribute_revision(attribute)

    if force:
        db.session.delete(option)
    else:
        option.deleted_at = datetime.now(timezone.utc)

    try:
        record_attribute_revision(attribute, action="update", created_by=principal.label, source=principal.via)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise_status(
            HTTPStatus.CONFLICT,
            detail={"message": "Attribute option is in use and cannot be deleted"},
        )
    return


@router.get(
    "/",
    response_model=List[AttributeOptionSchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_attribute_options",
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
    tags=[AgentTag.EXPOSED],
    operation_id="create_attribute_option",
    summary="Create attribute option",
    description="Create a new option for a specific attribute within a shop. The attribute_id must be provided in the request body.",
)
def create_option_v2(
    shop_id: UUID,
    data: AttributeOptionCreate = Body(...),
    principal: Principal = Depends(current_principal),
) -> AttributeOptionSchema:
    """Create a new option for an attribute within a shop.

    Validates that the attribute exists and belongs to the given shop.
    """
    # Ensure the attribute exists under the shop; lock it so concurrent option
    # writes serialize on attribute revision numbering
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=data.attribute_id, for_update=True)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute with id {data.attribute_id} not found for this shop")

    logger.info("Saving attribute option", attribute_id=str(data.attribute_id), value_key=data.value_key)

    ensure_baseline_attribute_revision(attribute)
    option = AttributeOptionTable(**data.model_dump())
    db.session.add(option)
    try:
        record_attribute_revision(attribute, action="update", created_by=principal.label, source=principal.via)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {data.value_key} already exists for this attribute")
    db.session.refresh(option)
    return option


@router.get(
    "/{option_id}",
    response_model=AttributeOptionSchema,
    tags=[AgentTag.EXPOSED],
    operation_id="get_attribute_option",
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
    tags=[AgentTag.EXPOSED],
    operation_id="update_attribute_option",
    summary="Update attribute option",
    description="Update the details of an existing attribute option, ensuring it belongs to the shop.",
)
def update_option_v2(
    shop_id: UUID,
    option_id: UUID,
    data: AttributeOptionUpdate = Body(...),
    principal: Principal = Depends(current_principal),
) -> AttributeOptionSchema:
    """Update an attribute option."""
    option = (
        db.session.query(AttributeOptionTable)
        .join(AttributeTable)
        .filter(AttributeOptionTable.id == option_id, AttributeTable.shop_id == shop_id)
        .first()
    )
    if not option:
        raise_status(HTTPStatus.NOT_FOUND, f"Option with id {option_id} not found for this shop")

    # Locked fetch instead of option.attribute: revision numbering must
    # serialize with concurrent option writes
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=option.attribute_id, for_update=True)
    ensure_baseline_attribute_revision(attribute)
    try:
        option = attribute_option_crud.update(db_obj=option, obj_in=data, commit=False)
        record_attribute_revision(attribute, action="update", created_by=principal.label, source=principal.via)
        db.session.commit()
        return option
    except IntegrityError:
        db.session.rollback()
        raise_status(HTTPStatus.CONFLICT, f"Option with value_key {data.value_key} already exists for this attribute")


@router.delete(
    "/{option_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_attribute_option",
    summary="Delete attribute option",
    description="Remove an attribute option, ensuring it belongs to the shop.",
)
def delete_option_v2(
    shop_id: UUID,
    option_id: UUID,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
    principal: Principal = Depends(current_principal),
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

    # Locked fetch instead of option.attribute: revision numbering must
    # serialize with concurrent option writes
    attribute = attribute_crud.get_id_by_shop_id(
        shop_id=shop_id, id=option.attribute_id, for_update=True, include_deleted=force
    )
    return _delete_option(attribute, option, force, principal)
