"""Endpoints for managing product attribute values within a shop context.

All routes are scoped by shop_id to ensure resources belong to the specified shop.
"""

from http import HTTPStatus
from typing import Any, List, Set, Union
from uuid import UUID

import structlog
from fastapi import APIRouter, Request
from fastapi.param_functions import Body, Depends
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_attribute import attribute_crud
from server.crud.crud_attribute_option import attribute_option_crud
from server.crud.crud_product import product_crud
from server.crud.crud_product_attribute_value import product_attribute_value_crud
from server.db import db
from server.db.models import AttributeOptionTable, AttributeTable, ProductAttributeValueTable, ProductTable
from server.schemas.product_attribute_value import (
    ProductAttributeOptionSelectionAdd,
    ProductAttributeOptionSelectionReplace,
    ProductAttributeValueBase,
    ProductAttributeValueSchema,
)
from server.security import auth_required
from server.services.revisions import actor, record_product_revision

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[ProductAttributeValueSchema],
    summary="List product attribute values",
    operation_id="product_attribute_values_list",
)
def list_product_attribute_values(
    shop_id: UUID, response: Response, common: dict = Depends(common_parameters)
) -> List[ProductAttributeValueSchema]:
    """List product attribute values for a shop (scoped by product.shop_id)."""
    # Build a base query scoped to the shop via product table
    query = (
        db.session.query(ProductAttributeValueTable)
        .join(ProductTable, ProductTable.id == ProductAttributeValueTable.product_id)
        .filter(ProductTable.shop_id == shop_id)
    )

    results, content_range = product_attribute_value_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
        query_parameter=query,
    )
    response.headers["Content-Range"] = content_range
    return results


@router.get(
    "/{id}",
    response_model=ProductAttributeValueSchema,
    summary="Get product attribute value",
    operation_id="product_attribute_values_get",
)
def get_product_attribute_value(shop_id: UUID, id: UUID) -> ProductAttributeValueSchema:
    """Retrieve a single product attribute value by id scoped to the given shop."""
    pav = product_attribute_value_crud.get(id)
    if not pav:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductAttributeValue with id {id} not found")
    # Ensure it belongs to the shop via product
    if not pav.product or pav.product.shop_id != shop_id:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductAttributeValue with id {id} not found for this shop")
    return pav


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    deprecated=True,
    summary="Create product attribute values (deprecated)",
    operation_id="product_attribute_values_create_deprecated",
)
def create_product_attribute_values(
    shop_id: UUID,
    request: Request,
    data: ProductAttributeValueBase = Body(...),
    principal: Any = Depends(auth_required),
) -> None:
    """
    DEPRECATED: Create a new product attribute value for a product within a shop.

    Notes:
    - This endpoint is deprecated; prefer using the selected options endpoint when possible.

    Validations:
    - Product exists and belongs to the shop
    """
    # Validate product belongs to shop
    product = product_crud.get_id_by_shop_id(shop_id=shop_id, id=data.product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product {data.product_id} not found for this shop")

    # Validate attribute belongs to shop
    attribute = attribute_crud.get_id_by_shop_id(shop_id=shop_id, id=data.attribute_id)
    if not attribute:
        raise_status(HTTPStatus.NOT_FOUND, f"Attribute {data.attribute_id} not found for this shop")

    # Validate option (if provided) belongs to attribute
    if data.option_id is not None:
        option = attribute_option_crud.get(id=data.option_id)
        if not option or option.attribute_id != data.attribute_id:
            raise_status(HTTPStatus.BAD_REQUEST, "Provided option_id does not belong to the given attribute")

    logger.info(
        "Saving product attribute value",
        product_id=str(data.product_id),
        attribute_id=str(data.attribute_id),
        option_id=str(data.option_id) if data.option_id else None,
    )

    # Prevent duplicates for the same product + attribute + option
    existing = product_attribute_value_crud.get_existing(
        product_id=data.product_id,
        attribute_id=data.attribute_id,
        option_id=data.option_id,
    )
    if existing:
        raise_status(HTTPStatus.CONFLICT, "Product attribute value already exists for this product/attribute/option")

    # Create + record a product revision in the same transaction
    db.session.add(ProductAttributeValueTable(**data.model_dump()))
    created_by, source = actor(principal, request)
    record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()


def get_attribute_options_by_ids(option_ids: list[UUID], shop_id: UUID) -> list[AttributeOptionTable]:
    options = (
        db.session.query(AttributeOptionTable)
        .join(AttributeTable, AttributeTable.id == AttributeOptionTable.attribute_id)
        .filter(
            AttributeOptionTable.id.in_(list(option_ids)),
            AttributeTable.shop_id == shop_id,
        )
        .all()
    )
    if len(options) != len(option_ids):
        raise_status(HTTPStatus.BAD_REQUEST, "One or more option IDs do not exist (or are not in this shop)")
    return options


@router.post(
    "/{product_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Create product attribute values for product",
    operation_id="product_attribute_values_create_for_product",
)
def create_product_attribute_values_for_product(
    shop_id: UUID,
    product_id: UUID,
    request: Request,
    data: ProductAttributeOptionSelectionAdd = Body(...),
    principal: Any = Depends(auth_required),
) -> None:
    """Create new product attribute value(s) for a specific product using product_id in the URL.

    This deprecates the old POST / endpoint that required product_id in the body.

    Notes:
    - attribute_id is omitted; it will be inferred from option_id, as the option is already tied to an attribute_id.

    - This endpoint first validates that all option_ids belong to attributes that belong to the shop.
    - And that these options actually exist.
    - If everything is passed, it will create the product attribute values.
    - Duplicates are ignored, and the endpoint returns 201 Created for each successful creation. That means no 409 is raised when a duplicate is encountered; it just won't be created.
    """
    # Validate and load provided options
    if not data.option_ids:
        raise_status(HTTPStatus.BAD_REQUEST, "option_ids must be a non-empty list")

    # Validate product belongs to shop via path param
    product = product_crud.get_id_by_shop_id(shop_id=shop_id, id=product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product {product_id} not found for this shop")

    options = get_attribute_options_by_ids(option_ids=data.option_ids, shop_id=shop_id)

    # Batch fetch existing PAVs for this product and these options
    existing_pavs = (
        db.session.query(ProductAttributeValueTable)
        .filter(
            ProductAttributeValueTable.product_id == product_id,
            ProductAttributeValueTable.option_id.in_([opt.id for opt in options]),
        )
        .all()
    )

    new_pavs = _create_product_attribute_values(product_id, options, {pav.option_id for pav in existing_pavs})

    if new_pavs:
        db.session.add_all(new_pavs)
        created_by, source = actor(principal, request)
        record_product_revision(product, action="update", created_by=created_by, source=source)
        db.session.commit()

    return None


def _create_product_attribute_values(
    product_id: UUID, options: List[AttributeOptionTable], existing_option_ids: Set[UUID]
) -> list[Any]:
    """
    Creates product attribute values by identifying new options that are not in the existing set
    of option IDs and preparing a list of product attribute value entries for these options.
    """
    new_pavs = []
    for option in options:
        if option.id not in existing_option_ids:
            logger.info(
                "Saving product attribute value (batch)",
                product_id=str(product_id),
                attribute_id=str(option.attribute_id),
                option_id=str(option.id),
            )
            new_pavs.append(
                ProductAttributeValueTable(
                    product_id=product_id,
                    attribute_id=option.attribute_id,
                    option_id=option.id,
                )
            )
    return new_pavs


@router.put(
    "/{product_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Replace product attribute values for product",
    operation_id="product_attribute_values_replace_for_product",
)
def put_selected_product_attribute_values_by_product(
    shop_id: UUID,
    product_id: UUID,
    request: Request,
    data: ProductAttributeOptionSelectionReplace = Body(...),
    principal: Any = Depends(auth_required),
) -> None:
    """New version of selected options endpoint addressed by product_id in the path.

    This endpoint now accepts option_ids that may belong to different attributes.
    Requirements/validations:
      - product_id (path) must belong to the shop
      - option_ids must be a non-empty list
      - all option_ids must exist
      - every inferred attribute (from the options) must belong to the shop
      - for each inferred attribute, set selected options for (product_id, attribute) to exactly
        the provided option_ids that belong to that attribute
    """
    # Validate and load provided options
    if not data.option_ids:
        raise_status(HTTPStatus.BAD_REQUEST, "option_ids must be a non-empty list")

    # Validate product belongs to shop using path param
    product = product_crud.get_id_by_shop_id(shop_id=shop_id, id=product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product {product_id} not found for this shop")

    options = get_attribute_options_by_ids(list(data.option_ids), shop_id)

    # Group selected options by their attribute_id. This also ended up making sure that the UUID/options_ids are `DISTINCT`
    attr_to_option_ids: dict[UUID, set[UUID]] = {}
    for opt in options:
        attr_to_option_ids.setdefault(opt.attribute_id, set()).add(opt.id)

    # Fetch all existing PAVs for this product and these attributes in one go
    existing_pavs = (
        db.session.query(ProductAttributeValueTable)
        .filter(
            ProductAttributeValueTable.product_id == product_id,
            ProductAttributeValueTable.attribute_id.in_(list(attr_to_option_ids.keys())),
        )
        .all()
    )

    # Group existing PAVs by attribute_id for easier processing
    attr_to_existing_pavs: dict[UUID, list[ProductAttributeValueTable]] = {}
    for pav in existing_pavs:
        attr_to_existing_pavs.setdefault(pav.attribute_id, []).append(pav)

    to_add_objs = []
    to_delete_objs = []

    # Process each attribute group
    for inferred_attribute_id, option_ids_for_attr in attr_to_option_ids.items():
        existing_for_attr = attr_to_existing_pavs.get(inferred_attribute_id, [])
        existing_option_ids = {row.option_id for row in existing_for_attr if row.option_id is not None}

        to_add = option_ids_for_attr - existing_option_ids
        for row in existing_for_attr:
            if row.option_id not in option_ids_for_attr:
                logger.info(
                    "Deleting product attribute value (batch replace)",
                    product_id=str(row.product_id),
                    attribute_id=str(row.attribute_id),
                    option_id=str(row.option_id),
                    pav_id=str(row.id),
                )
                to_delete_objs.append(row)

        for option_id in to_add:
            logger.info(
                "Saving product attribute value (batch replace)",
                product_id=str(product_id),
                attribute_id=str(inferred_attribute_id),
                option_id=str(option_id),
            )
            to_add_objs.append(
                ProductAttributeValueTable(
                    product_id=product_id,
                    attribute_id=inferred_attribute_id,
                    option_id=option_id,
                )
            )

    # Batch execute changes
    if to_add_objs:
        db.session.add_all(to_add_objs)
    for obj in to_delete_objs:
        db.session.delete(obj)

    if to_add_objs or to_delete_objs:
        created_by, source = actor(principal, request)
        record_product_revision(product, action="update", created_by=created_by, source=source)
        db.session.commit()

    return None


@router.delete(
    "/{id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete product attribute value",
    operation_id="product_attribute_values_delete",
)
def delete_product_attribute_value(
    shop_id: UUID, id: UUID, request: Request, principal: Any = Depends(auth_required)
) -> None:
    """Delete a product attribute value if it belongs to the given shop."""
    pav = product_attribute_value_crud.get(id)
    if not pav:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductAttributeValue with id {id} not found")
    if not pav.product or pav.product.shop_id != shop_id:
        raise_status(HTTPStatus.NOT_FOUND, f"ProductAttributeValue with id {id} not found for this shop")
    product = pav.product
    db.session.delete(pav)
    created_by, source = actor(principal, request)
    record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()
    return None
