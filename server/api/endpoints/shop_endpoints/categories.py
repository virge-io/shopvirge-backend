import json
from collections import defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, List, Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.param_functions import Body, Depends
from sqlalchemy import func
from sqlalchemy.orm import aliased
from starlette.responses import Response

from server.agent_tags import AgentTag
from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.api.helpers import invalidateShopCache
from server.crud import crud_shop
from server.crud.crud_category import category_crud
from server.crud.crud_product import product_crud
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeTable,
    AttributeTranslationTable,
    CategoryTable,
    ProductAttributeValueTable,
    ProductTable,
)
from server.schemas.attribute import (
    AttributeTranslationBase,
    AvailableAttributeSchema,
    AvailableOptionSchema,
)
from server.schemas.category import (
    CategoryCreate,
    CategoryIsDeletable,
    CategoryOrder,
    CategorySchema,
    CategoryUpdate,
    CategoryWithNames,
)
from server.schemas.product import (
    AttributeFilters,
    ProductWithAttributes,
    ProductWithDefaultPrice,
)
from server.schemas.product_attribute import ProductAttributeItem
from server.security import auth_required_any
from server.services.revisions import actor, record_category_revision, record_product_revision

logger = structlog.get_logger(__name__)

router = APIRouter()
public_router = APIRouter()


def get_shop(shop_id: UUID):
    shop = crud_shop.get_id(id=shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop


@router.get(
    "/",
    response_model=List[CategorySchema],
    tags=[AgentTag.EXPOSED, AgentTag.LARGE],
    operation_id="list_categories",
    summary="List categories",
    description="Returns paginated categories for a shop, ordered by `order_number`. Supports filtering and sorting.",
)
def get_multi(shop_id: UUID, response: Response, common: dict = Depends(common_parameters)) -> List[CategorySchema]:
    # shop = get_shop(shop_id)
    categories, header_range = category_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
    )
    response.headers["Content-Range"] = header_range
    return categories


@router.get(
    "/{category_id}",
    response_model=CategorySchema,
    tags=[AgentTag.EXPOSED],
    operation_id="get_category",
    summary="Get category",
    description="Retrieve a single category by its UUID within a shop.",
)
def get_by_id(shop_id: UUID, category_id: UUID) -> CategorySchema:
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with id {category_id} not found")
    return category


# @router.get("/is-deletable/{id}", response_model=CategoryIsDeletable)
# def get_id(id: UUID) -> CategoryIsDeletable:
#     shop_to_price = shop_to_price_crud.get_shops_to_prices_by_category(category_id=id)
#     if shop_to_price:
#         return CategoryIsDeletable(is_deletable=False)
#     else:
#         return CategoryIsDeletable(is_deletable=True)


@router.get(
    "/name/{name}",
    response_model=CategorySchema,
    summary="Get category by name",
    description="Retrieve a category using its human-readable name (exact match, case-sensitive).",
)
def get_by_name(name: str, shop_id: UUID) -> CategorySchema:
    category = category_crud.get_by_name(name=name, shop_id=shop_id)

    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with name {name} not found")
    return category


@router.post(
    "/",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="create_category",
    summary="Create category",
    description="Add a new category to a shop. The `order_number` is automatically set to the next available value.",
)
def create(
    shop_id: UUID, request: Request, data: CategoryCreate = Body(...), principal: Any = Depends(auth_required_any)
) -> None:
    category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.desc()).first()
    data.order_number = (category.order_number + 1) if category is not None else 0

    logger.info("Saving category", data=data)
    created_by, source = actor(principal, request)
    category = category_crud.create_by_shop_id(obj_in=data, shop_id=shop_id, commit=False)
    record_category_revision(category, action="create", created_by=created_by, source=source)
    db.session.commit()
    db.session.refresh(category)
    return category


@router.put(
    "/{category_id}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="update_category",
    summary="Update category",
    description="Update an existing category's details and translations.",
)
def update(
    *,
    category_id: UUID,
    shop_id: UUID,
    item_in: CategoryUpdate,
    request: Request,
    principal: Any = Depends(auth_required_any),
) -> Any:
    category = category_crud.get_id_by_shop_id(shop_id, category_id, for_update=True)
    logger.info("Updating category", data=category)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    created_by, source = actor(principal, request)
    category = category_crud.update(
        db_obj=category,
        obj_in=item_in,
        commit=False,
    )
    record_category_revision(category, action="update", created_by=created_by, source=source)
    db.session.commit()

    # if category.shop_id is not None:
    #     invalidateShopCache(category.shop_id)

    return category


@router.put(
    "/{category_id}/swap",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    summary="Reorder category",
    description="Move a category up (`move_up=true`) or down (`move_up=false`) in the display order. Swaps `order_number` with the adjacent category.",
)
def swap(shop_id: UUID, category_id: UUID, move_up: bool):
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    last_category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.desc()).first()

    first_category = CategoryTable.query.filter_by(shop_id=shop_id).order_by(CategoryTable.order_number.asc()).first()

    old_order_number = category.order_number
    new_order_number = None

    if move_up:
        if old_order_number == first_category.order_number:
            raise HTTPException(status_code=400, detail="Cannot move up further - Minimum order number achieved.")
        new_order_number = old_order_number - 1
    else:
        if old_order_number == last_category.order_number:
            raise HTTPException(status_code=400, detail="Cannot move down further - Maximum order number achieved.")
        new_order_number = old_order_number + 1

    category_to_swap = CategoryTable.query.filter_by(shop_id=shop_id).filter_by(order_number=new_order_number).first()

    if category_to_swap is not None:
        category_crud.update(db_obj=category_to_swap, obj_in=CategoryOrder(order_number=old_order_number), commit=False)

    category_crud.update(db_obj=category, obj_in=CategoryOrder(order_number=new_order_number))

    return HTTPStatus.CREATED


@router.delete(
    "/{category_id}",
    response_model=None,
    status_code=HTTPStatus.NO_CONTENT,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_category",
    summary="Delete category (moves to trash)",
    description=(
        "Moves a category to the trash (restorable with `restore_category`). If products are still "
        "assigned to it the request fails with 409 and the product count; retry with `force=true` to "
        "also move all those products to the trash (restorable as one batch), or with `detach=true` to "
        "keep the products but clear their category. `force` and `detach` are mutually exclusive."
    ),
)
def delete(
    category_id: UUID,
    shop_id: UUID,
    request: Request,
    force: bool = Query(False, description="Also move all products in this category to the trash."),
    detach: bool = Query(False, description="Keep the products; clear their category reference instead."),
    principal: Any = Depends(auth_required_any),
) -> None:
    if force and detach:
        raise HTTPException(status_code=422, detail="force and detach are mutually exclusive")

    category = category_crud.get_id_by_shop_id(shop_id, category_id, for_update=True)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    products = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id, ProductTable.category_id == category_id)
        .with_for_update()
        .all()
    )

    if products and not force and not detach:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Category still has {len(products)} product(s); deleting it affects all of them.",
                "product_count": len(products),
                "hint": (
                    "Retry with force=true to move the products to the trash too (restorable as one batch), "
                    "or detach=true to keep the products without a category."
                ),
            },
        )

    created_by, source = actor(principal, request)
    now = datetime.now(timezone.utc)
    extra_data = None

    if products and force:
        batch_id = uuid4()
        for product in products:
            record_product_revision(product, action="delete", created_by=created_by, source=source)
            product.deleted_at = now
            product.deleted_batch_id = batch_id
        extra_data = {"deleted_batch_id": str(batch_id), "deleted_product_count": len(products)}
    elif products and detach:
        category_name = category.translation.main_name if category.translation else None
        detached_from = {"id": str(category_id), "name": category_name}
        for product in products:
            product.category_id = None
            record_product_revision(
                product,
                action="update",
                created_by=created_by,
                source=source,
                extra_data={"detached_from_category": detached_from},
            )
        extra_data = {"detached_product_count": len(products)}

    record_category_revision(category, action="delete", created_by=created_by, source=source, extra_data=extra_data)
    category.deleted_at = now
    db.session.commit()
    return None


@public_router.get(
    "/{category_id}/available-attributes",
    response_model=list[AvailableAttributeSchema],
    summary="Get available filter attributes for a category",
    description="Returns attributes actually used by products in this category, with option counts. Pass option_id[] to narrow counts to the already-selected filters (AND logic).",
)
def get_available_attributes(
    shop_id: UUID,
    category_id: UUID,
    option_id: List[UUID] = Query(None),
) -> list[AvailableAttributeSchema]:
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with id {category_id} not found")

    shop = shop_crud.get(shop_id)
    if shop and isinstance(shop.config, str):
        shop.config = json.loads(shop.config)

    # Build a subquery of product IDs that match the active filters
    product_subq = (
        db.session.query(ProductTable.id)
        .filter(ProductTable.shop_id == shop_id)
        .filter(ProductTable.category_id == category_id)
        .filter(ProductTable.price.isnot(None))
    )
    if shop and shop.config.get("toggles", {}).get("enable_stock_on_products"):
        product_subq = product_subq.filter(ProductTable.stock > 0)
    # Each selected option_id is ANDed: products must carry all of them
    if option_id:
        for opt in option_id:
            pav_alias = aliased(ProductAttributeValueTable)
            product_subq = product_subq.join(pav_alias, ProductTable.id == pav_alias.product_id).filter(
                pav_alias.option_id == opt
            )
    product_subq = product_subq.subquery()

    # Aggregation query: count per attribute option across the filtered product set
    results = (
        db.session.query(
            AttributeTable.id.label("attribute_id"),
            AttributeTable.name.label("attribute_name"),
            AttributeTable.unit.label("attribute_unit"),
            AttributeOptionTable.id.label("option_id"),
            AttributeOptionTable.value_key.label("option_value_key"),
            func.count(ProductAttributeValueTable.id).label("product_count"),
        )
        .join(ProductAttributeValueTable, ProductAttributeValueTable.attribute_id == AttributeTable.id)
        .join(product_subq, product_subq.c.id == ProductAttributeValueTable.product_id)
        .join(AttributeOptionTable, AttributeOptionTable.id == ProductAttributeValueTable.option_id)
        .group_by(
            AttributeTable.id,
            AttributeTable.name,
            AttributeTable.unit,
            AttributeOptionTable.id,
            AttributeOptionTable.value_key,
        )
        .all()
    )

    if not results:
        return []

    # Batch-load translations for the distinct attribute IDs
    attr_ids = list({r.attribute_id for r in results})
    translations = (
        db.session.query(AttributeTranslationTable).filter(AttributeTranslationTable.attribute_id.in_(attr_ids)).all()
    )
    trans_by_attr = {t.attribute_id: t for t in translations}

    # Assemble nested response grouped by attribute
    attrs_dict: dict[UUID, AvailableAttributeSchema] = {}
    for row in results:
        if row.attribute_id not in attrs_dict:
            trans = trans_by_attr.get(row.attribute_id)
            translation = (
                AttributeTranslationBase(
                    main_name=trans.main_name,
                    alt1_name=trans.alt1_name,
                    alt2_name=trans.alt2_name,
                )
                if trans
                else None
            )
            attrs_dict[row.attribute_id] = AvailableAttributeSchema(
                id=row.attribute_id,
                name=row.attribute_name,
                unit=row.attribute_unit,
                translation=translation,
                options=[],
            )
        attrs_dict[row.attribute_id].options.append(
            AvailableOptionSchema(
                id=row.option_id,
                value_key=row.option_value_key,
                product_count=row.product_count,
            )
        )

    return list(attrs_dict.values())


@public_router.get(
    "/{category_id}/products",
    response_model=List[ProductWithAttributes],
    summary="List products in a category with attribute filters",
    description="""
Fetch products in a category along with their attributes. Supports attribute-based filtering.

Attribute filters (mutually exclusive — only one can be used at a time):
* `option_id` array[UUID]: Filter by attribute option UUIDs.
* `attribute_id` UUID: Filter by attribute UUID.
* `option_value_key` array[str]: Filter by option value keys (e.g., 'S', 'RED').
* `attribute_name` str: Filter by attribute name.
""",
)
def get_category_products(
    shop_id: UUID,
    category_id: UUID,
    response: Response,
    option_id: List[UUID] = Query(None),
    attribute_id: Optional[UUID] = Query(None),
    option_value_key: List[str] = Query(None),
    attribute_name: Optional[str] = Query(None),
    common: dict = Depends(common_parameters),
) -> List[ProductWithAttributes]:
    category = category_crud.get_id_by_shop_id(shop_id, category_id)
    if not category:
        raise_status(HTTPStatus.NOT_FOUND, f"Category with id {category_id} not found")

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

    # Base query: products for this shop scoped to this category
    base_query = (
        db.session.query(ProductTable)
        .filter(ProductTable.shop_id == shop_id)
        .filter(ProductTable.category_id == category_id)
    )

    products, header_range = product_crud.get_multi_by_shop_id(
        shop_id=shop_id,
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=filter_parameters,
        sort_parameters=common["sort"],
        query_parameter=base_query,
    )
    response.headers["Content-Range"] = header_range

    if not products:
        return []

    # Calculate images_amount
    for product in products:
        product.images_amount = 0
        for i in [1, 2, 3, 4, 5, 6]:
            if getattr(product, f"image_{i}"):
                product.images_amount += 1

    # Build response with attributes
    out: List[ProductWithAttributes] = []
    for p in products:
        attrs: list[ProductAttributeItem] = []
        for pav in getattr(p, "attribute_values", []) or []:
            attribute = getattr(pav, "attribute", None)
            option = getattr(pav, "option", None)
            attr_name = None
            if attribute is not None:
                translation = getattr(attribute, "translation", None)
                attr_name = getattr(translation, "main_name", None) or getattr(attribute, "name", None)
            attrs.append(
                ProductAttributeItem(
                    attribute_id=getattr(attribute, "id", None),
                    attribute_name=attr_name,
                    option_id=getattr(option, "id", None),
                    option_value_key=getattr(option, "value_key", None),
                )
            )

        prod_schema = ProductWithDefaultPrice.model_validate(p)
        out.append(ProductWithAttributes(product=prod_schema, attributes=attrs))

    # Adjust Content-Range header to reflect actual count
    try:
        kind, rest = header_range.split(" ", 1)
        range_part, total_part = rest.split("/")
        start, end = [int(x) for x in range_part.split("-")]
        if out:
            end = start + len(out) - 1
        else:
            end = start - 1
        response.headers["Content-Range"] = f"{kind} {start}-{end}/{total_part}"
    except Exception:
        pass

    return out
