import json
from http import HTTPStatus
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from fastapi.param_functions import Depends
from sqlalchemy import func
from sqlalchemy.orm import aliased
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_category import category_crud
from server.crud.crud_product import product_crud
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.models import (
    AttributeOptionTable,
    AttributeTable,
    AttributeTranslationTable,
    ProductAttributeValueTable,
    ProductTable,
)
from server.schemas.attribute import (
    AttributeTranslationBase,
    AvailableAttributeSchema,
    AvailableOptionSchema,
)
from server.schemas.product import (
    AttributeFilters,
    ProductWithAttributes,
    ProductWithDefaultPrice,
)
from server.schemas.product_attribute import ProductAttributeItem

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
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


@router.get(
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
    except Exception:  # noqa: S110 -- best-effort header; on failure leave it as-is
        pass

    return out
