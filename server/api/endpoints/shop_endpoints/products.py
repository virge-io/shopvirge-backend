import json
from datetime import datetime, timezone
from http import HTTPStatus
from textwrap import dedent
from typing import Any, List, Literal, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api import deps
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud import crud_shop
from server.crud.crud_product import product_crud
from server.db import db
from server.db.models import ApiKeyTable, ProductTable, ProductTranslationTable
from server.schemas.product import (
    AttributeFilters,
    ProductCreate,
    ProductOrder,
    ProductSchema,
    ProductUpdate,
    ProductWithAttributes,
    ProductWithDefaultPrice,
    ProductWithDetailsAndPrices,
)
from server.schemas.product_attribute import ProductAttributeItem
from server.schemas.shop import Toggles
from server.security import auth_required_any
from server.services.revisions import actor, record_product_revision

logger = structlog.get_logger(__name__)

router = APIRouter()
public_router = APIRouter()


def get_shop(shop_id: UUID):
    shop = crud_shop.shop_crud.get(id=shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


def _assert_unique_name(shop_id: UUID, main_name: str, exclude_product_id: UUID | None = None) -> None:
    query = (
        db.session.query(ProductTable)
        .join(ProductTranslationTable, ProductTranslationTable.product_id == ProductTable.id)
        .filter(ProductTable.shop_id == shop_id, ProductTranslationTable.main_name == main_name)
    )
    if exclude_product_id:
        query = query.filter(ProductTable.id != exclude_product_id)
    if query.first():
        raise_status(HTTPStatus.CONFLICT, f"A product named '{main_name}' already exists in this shop")


@router.get(
    "/",
    response_model=List[ProductWithDefaultPrice],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_products",
    summary="List products",
    description="Returns paginated products for a shop, each with its default price. Supports filtering (e.g. `featured:true`, `category_id:<uuid>`) and sorting via common query parameters.",
)
def get_multi(
    shop_id: UUID,
    response: Response,
    stock_status: Literal["in_stock", "out_of_stock", "all"] = Query(
        "all",
        description=(
            "Filter products by inventory state. `in_stock` returns products with stock > 0, "
            "`out_of_stock` returns products with stock = 0, `all` (default) returns everything."
        ),
    ),
    common: dict = Depends(common_parameters),
) -> List[ProductWithDefaultPrice]:
    products, header_range = product_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
        stock_status=stock_status,
    )
    response.headers["Content-Range"] = header_range

    for product in products:
        product.images_amount = 0
        for i in [1, 2, 3, 4, 5, 6]:
            if getattr(product, f"image_{i}"):
                product.images_amount += 1

    return products


@router.get(
    "/with_attributes",
    response_model=List[ProductWithAttributes],
    summary="List products with attributes",
    description="""
Fetch a list of products along with their associated attributes.

You can filter the results using one of the following mutually exclusive attribute filters:

* `option_id` array[UUID]: Filter by one or multiple attribute option UUIDs.
* `attribute_id` UUID: Filter by attribute UUID.
* `option_value_key` array[str]: Filter by option value (e.g., 'Red', 'XL').
* `attribute_name` array[str]: Filter by one or multiple attribute names (e.g., 'Color', 'Size').

Only one attribute filter can be used at a time.

You can additionally narrow results by inventory state with `stock_status`:
`in_stock` (stock > 0), `out_of_stock` (stock = 0), or `all` (default).
""",
)
def get_multi_with_attributes(
    shop_id: UUID,
    response: Response,
    option_id: List[UUID] = Query(None),
    attribute_id: UUID = Query(None),
    option_value_key: List[str] = Query(None),
    attribute_name: str = Query(None),
    stock_status: Literal["in_stock", "out_of_stock", "all"] = Query(
        "all",
        description=(
            "Filter products by inventory state. `in_stock` returns products with stock > 0, "
            "`out_of_stock` returns products with stock = 0, `all` (default) returns everything."
        ),
    ),
    common: dict = Depends(common_parameters),
) -> List[ProductWithAttributes]:
    attribute_filters = AttributeFilters(
        option_id=option_id,
        attribute_id=attribute_id,
        option_value_key=option_value_key,
        attribute_name=attribute_name,
    )
    filter_parameters = common["filter"] or []

    for name, value in attribute_filters.model_dump(exclude_none=True).items():
        if isinstance(value, list):
            for v in value:
                filter_parameters.append(f"{name}:{v}")
        else:
            filter_parameters.append(f"{name}:{value}")

    # Base: fetch paginated products for this shop
    products, header_range = product_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=filter_parameters,
        sort_parameters=common["sort"],
        stock_status=stock_status,
    )
    # We will update Content-Range if filtering by option_id changes the visible count
    response.headers["Content-Range"] = header_range

    if not products:
        return []

    # Calculate images_amount
    for product in products:
        product.images_amount = 0
        for i in [1, 2, 3, 4, 5, 6]:
            if getattr(product, f"image_{i}"):
                product.images_amount += 1

    # Build response preserving order, using ORM relationships
    out: List[ProductWithAttributes] = []
    for p in products:
        attrs: list[ProductAttributeItem] = []
        pavs = getattr(p, "attribute_values", []) or []
        for pav in pavs:
            attribute = getattr(pav, "attribute", None)
            option = getattr(pav, "option", None)
            attribute_name = None
            if attribute is not None:
                translation = getattr(attribute, "translation", None)
                attribute_name = getattr(translation, "main_name", None) or getattr(attribute, "name", None)
            attrs.append(
                ProductAttributeItem(
                    attribute_id=getattr(attribute, "id", None),
                    attribute_name=attribute_name,
                    option_id=getattr(option, "id", None),
                    option_value_key=getattr(option, "value_key", None),
                )
            )

        prod_schema = ProductWithDefaultPrice.model_validate(p)
        out.append(
            ProductWithAttributes(
                product=prod_schema,
                attributes=attrs,
            )
        )

    # Adjust Content-Range count to reflect filtered number within page (keeps total as-is)
    try:
        # header_range format expected: "items start-end/total"
        kind, rest = header_range.split(" ", 1)
        range_part, total_part = rest.split("/")
        start, end = [int(x) for x in range_part.split("-")]
        # Keep start the same, recompute end based on returned count
        if out:
            end = start + len(out) - 1
        else:
            end = start - 1
        response.headers["Content-Range"] = f"{kind} {start}-{end}/{total_part}"
    except Exception:
        # If parsing fails, leave header as-is
        pass

    return out


@public_router.get(
    "/{product_id}/with_attributes",
    response_model=ProductWithAttributes,
    summary="Get product with attributes",
    description="Retrieve a single product together with its assigned attribute values (e.g. size, color). Public endpoint — no authentication required.",
)
def get_by_id_with_attributes(product_id: UUID, shop_id: UUID) -> ProductWithAttributes:
    product = product_crud.get_id_by_shop_id(shop_id, product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {product_id} not found")

    product.images_amount = 0
    for i in [1, 2, 3, 4, 5, 6]:
        if getattr(product, f"image_{i}"):
            product.images_amount += 1

    attrs: list[ProductAttributeItem] = []
    for pav in getattr(product, "attribute_values", []) or []:
        attribute = getattr(pav, "attribute", None)
        option = getattr(pav, "option", None)
        attribute_name = None
        if attribute is not None:
            translation = getattr(attribute, "translation", None)
            attribute_name = getattr(translation, "main_name", None) or getattr(attribute, "name", None)
        attrs.append(
            ProductAttributeItem(
                attribute_id=getattr(attribute, "id", None),
                attribute_name=attribute_name,
                option_id=getattr(option, "id", None),
                option_value_key=getattr(option, "value_key", None),
            )
        )

    prod_schema = ProductWithDefaultPrice.model_validate(product)
    return ProductWithAttributes(product=prod_schema, attributes=attrs)


@public_router.get(
    "/{product_id}",
    response_model=ProductWithDetailsAndPrices,
    tags=[AgentTag.EXPOSED],
    operation_id="get_product",
    summary="Get product",
    description="Retrieve full product details including all active prices, translations, and images. Public endpoint — no authentication required.",
)
def get_by_id(product_id: UUID, shop_id: UUID) -> ProductWithDetailsAndPrices:
    product = product_crud.get_id_by_shop_id(shop_id, product_id)
    if not product:
        raise_status(HTTPStatus.NOT_FOUND, f"Product with id {product_id} not found")

    product.images_amount = 0
    for i in [1, 2, 3, 4, 5, 6]:
        if getattr(product, f"image_{i}"):
            product.images_amount += 1

    return product


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="create_product",
    summary="Create product",
    description="Add a new product to a shop category. The `order_number` is automatically set to the next available value within the category.",
)
def create(
    shop_id: UUID,
    request: Request,
    data: ProductCreate = Body(...),
    principal: Any = Depends(auth_required_any),
) -> None:
    shop = get_shop(shop_id)
    raw = json.loads(shop.config) if isinstance(shop.config, str) else (shop.config or {})
    toggles = Toggles.model_validate(raw.get("toggles", {}) if isinstance(raw, dict) else {})
    if toggles.force_unique_product_names:
        _assert_unique_name(shop_id, data.translation.main_name)

    product = (
        ProductTable.query.filter_by(shop_id=shop_id)
        .filter_by(category_id=data.category_id)
        .order_by(ProductTable.order_number.desc())
        .first()
    )
    data.order_number = (product.order_number + 1) if product is not None else 0

    logger.info("Saving product", data=data)
    created_by, source = actor(principal, request)
    try:
        product = product_crud.create_by_shop_id(obj_in=data, shop_id=shop_id, commit=False)
        db.session.flush()
        record_product_revision(product, action="create", created_by=created_by, source=source)
        db.session.commit()
        db.session.refresh(product)
    except IntegrityError:
        db.session.rollback()
        raise_status(HTTPStatus.CONFLICT, f"A product with SKU '{data.sku}' already exists in this shop")
    return product


@router.put(
    "/{product_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="update_product",
    summary="Update product",
    description="Update an existing product's details, including name, description, pricing, stock, and feature flags.",
)
def update(
    *,
    product_id: UUID,
    shop_id: UUID,
    item_in: ProductUpdate,
    request: Request,
    principal: Any = Depends(auth_required_any),
) -> Any:
    product = product_crud.get_id_by_shop_id(shop_id, product_id, for_update=True)
    logger.info("Updating product", data=product)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    shop = get_shop(shop_id)
    raw = json.loads(shop.config) if isinstance(shop.config, str) else (shop.config or {})
    toggles = Toggles.model_validate(raw.get("toggles", {}) if isinstance(raw, dict) else {})
    if toggles.force_unique_product_names:
        _assert_unique_name(shop_id, item_in.translation.main_name, exclude_product_id=product_id)

    item_in.modified_at = datetime.now(timezone.utc)

    created_by, source = actor(principal, request)
    product = product_crud.update(
        db_obj=product,
        obj_in=item_in,
        commit=False,
    )
    db.session.flush()
    record_product_revision(product, action="update", created_by=created_by, source=source)
    db.session.commit()
    return product


@router.put(
    "/{product_id}/swap",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Reorder product",
    description="Move a product up (`move_up=true`) or down (`move_up=false`) in the display order within its category. Swaps `order_number` with the adjacent product.",
)
def swap(shop_id: UUID, product_id: UUID, move_up: bool):
    product = product_crud.get_id_by_shop_id(shop_id, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    last_product = (
        ProductTable.query.filter_by(shop_id=shop_id)
        .filter_by(category_id=product.category_id)
        .order_by(ProductTable.order_number.desc())
        .first()
    )

    first_product = (
        ProductTable.query.filter_by(shop_id=shop_id)
        .filter_by(category_id=product.category_id)
        .order_by(ProductTable.order_number.asc())
        .first()
    )

    old_order_number = product.order_number
    new_order_number = None

    if move_up:
        if old_order_number == first_product.order_number:
            raise HTTPException(status_code=400, detail="Cannot move up further - Minimum order number achieved.")
        new_order_number = old_order_number - 1
    else:
        if old_order_number == last_product.order_number:
            raise HTTPException(status_code=400, detail="Cannot move down further - Maximum order number achieved.")
        new_order_number = old_order_number + 1

    product_to_swap = (
        ProductTable.query.filter_by(shop_id=shop_id)
        .filter_by(category_id=product.category_id)
        .filter_by(order_number=new_order_number)
        .first()
    )

    if product_to_swap is not None:
        product_crud.update(db_obj=product_to_swap, obj_in=ProductOrder(order_number=old_order_number), commit=False)

    product_crud.update(db_obj=product, obj_in=ProductOrder(order_number=new_order_number))

    return HTTPStatus.CREATED


@router.delete(
    "/{product_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_product",
    summary="Delete product (moves to trash)",
    description=(
        "Moves the product to the trash. The product disappears from all listings but can be "
        "restored with `restore_product` or via its revisions — this action is reversible. "
        "Only `force=true` permanently purges the product; that is irreversible and requires "
        "user (Cognito) credentials — API keys get 403."
    ),
)
def delete(
    product_id: UUID,
    shop_id: UUID,
    request: Request,
    force: bool = Query(False, description="Permanently purge instead of moving to trash. Irreversible."),
    principal: Any = Depends(auth_required_any),
) -> None:
    product = product_crud.get_id_by_shop_id(shop_id, product_id, for_update=True, include_deleted=force)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if force:
        if isinstance(principal, ApiKeyTable):
            raise HTTPException(
                status_code=403,
                detail="Purging a product is irreversible and requires user credentials; API keys may only trash.",
            )
        # Hard purge: removes the row (+ translation, tag links, attribute values via
        # cascades). Revision rows are intentionally kept.
        return product_crud.delete_by_shop_id(shop_id=shop_id, id=product_id, include_deleted=True)

    created_by, source = actor(principal, request)
    record_product_revision(product, action="delete", created_by=created_by, source=source)
    product.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return None
